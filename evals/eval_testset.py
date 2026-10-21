"""챗봇 평가 — 평가셋 56문항(testset_2026.json)으로 판정·되묻기·위기 감지·검색·여러 턴 대화를 채점한다.

두 가지 모드:
    engine (기본, Claude 호출 없음 — 무료)
        eligibility  손계산 정답 가구를 판정 엔진에 직접 넣어 소득인정액·충족 여부가 맞는지
        ask          부분 조건에서 되물을 조건 목록(missing_fields)이 맞는지
        crisis       전 문항에 위기 감지 규칙을 돌려 종류가 맞는지 (정답 null = 오탐 검사)
        info         질문으로 검색해 5등 안에 정답 쪽이 나오는지 (Hit@5)
        multiturn    알아듣기 결과(understood)를 정답대로 넣은 챗봇으로 대화 한 편 — 되묻기 순서·가정·탈출·중단·판정
    chat (--chat, Claude 호출 — 유료. 2026-10 실측: Opus 로 약 120회 호출 — 크레딧이 적으면 --ids 로 일부만)
        질문을 챗봇에 그대로 보내 "Claude 가 조건을 제대로 알아듣고 → 엔진 판정까지 맞게 가는지"를 본다.
        info 문항은 답변·검색 문맥을 저장해 RAGAS 채점(evals/eval_ragas.py)의 입력으로 쓴다.

사용법 (DB 실행 + 기준 중위소득·청크 적재 필요):
    python -m evals.eval_testset                    engine 모드
    python -m evals.eval_testset --chat             chat 모드 (.env 의 ANTHROPIC_API_KEY)
    python -m evals.eval_testset --chat --ids 1,2,36   일부 문항만
결과: evals/results/testset_engine.json / testset_chat.json
"""

import argparse
import json
import sys
import uuid
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from app.chat.crisis import detect
from app.chat.state import ASSET_FIELDS, HouseholdInfo, missing_fields, to_household

EVAL_DIR = Path(__file__).resolve().parent
TESTSET_PATH = EVAL_DIR / "testset_2026.json"
RESULTS_DIR = EVAL_DIR / "results"
TOP_K = 5  # 챗봇이 Claude 에 넘기는 청크 수


def load_items(ids: set[int] | None = None) -> list[dict]:
    items = json.loads(TESTSET_PATH.read_text(encoding="utf-8"))["items"]
    return [it for it in items if ids is None or it["id"] in ids]


def full_household(item: dict) -> HouseholdInfo:
    """eligibility 문항의 가구 — 적지 않은 칸은 0 (질문이 소득·재산을 다 말했으므로)."""
    filled = {f: 0 for f in ("earned_income", "other_income", *ASSET_FIELDS)} | item["household"]
    return HouseholdInfo(**filled)


def compare_judgements(expected: dict, actual: list[dict]) -> dict:
    """정답 {제도: {recognized_income, eligible}} vs 판정 결과 목록 → 채점 한 줄."""
    got = {r["program"]: r for r in actual}
    wrong = []
    for program, exp in expected.items():
        r = got.get(program)
        if r is None:
            wrong.append(f"{program}: 판정 없음")
        elif r["eligible"] != exp["eligible"] or r["recognized_income"] != exp["recognized_income"]:
            wrong.append(f"{program}: 소득인정액 {r['recognized_income']:,} / {'충족' if r['eligible'] else '미충족'}"
                         f" (정답 {exp['recognized_income']:,} / {'충족' if exp['eligible'] else '미충족'})")
    eligible_ok = sum(1 for p, exp in expected.items() if p in got and got[p]["eligible"] == exp["eligible"])
    return {"pass": not wrong, "programs": len(expected), "eligible_ok": eligible_ok, "wrong": wrong}


# ── 여러 턴 대화 (multiturn) — engine·chat 모드 공통 ──────────────


def run_multiturn(item: dict, bot, thread_id: str) -> dict:
    """대화 한 편을 턴마다 보내고 채점한다.

    턴마다: 되물은 조건(pending_fields)이 정답 "ask" 와 같은지 ([] = 되묻지 않음), 위기 신호
    끝에:   outcome — 안내 문구가 아니라 마지막 대화 상태로 판단한다 (문구를 바꿔도 채점이 안 깨지게)
        judged    판정이 정답과 같고, 가정한 조건(assumed)도 같음
        give_up   판정을 멈춤 (state.gave_up — 정답에 "gave_up" 이 있으면 조건도 같아야 함)
        answered  마지막 말을 새 설명 질문(intent=info)으로 받아 답함 — 되묻기·판정·판정 멈춤이 아님
    """
    asks, crises = [], []
    try:
        for turn in item["turns"]:
            reply = bot.send(thread_id, turn["user"])
            state = bot.graph.get_state({"configurable": {"thread_id": thread_id}}).values
            asks.append(state.get("pending_fields") if reply.waiting else [])
            crises.append(reply.crisis or None)
    except ScriptError as e:  # engine 모드 대본이 그래프 흐름과 어긋남 = 흐름이 정답과 다름
        return {"pass": False, "asks": asks, "wrong": [str(e)], "crisis_found": next(filter(None, crises), None)}
    expected_asks = [t["ask"] for t in item["turns"]]
    wrong = [f"{i}턴 되물음 {got} (정답 {exp})" for i, (got, exp) in enumerate(zip(asks, expected_asks), start=1) if got != exp]

    gave_up = state.get("gave_up") or []
    outcome = item["outcome"]
    if outcome == "judged":
        if reply.eligibility:
            wrong += compare_judgements(item["expected"], reply.eligibility)["wrong"]
            if set(state.get("assumed") or []) != set(item.get("assumed", [])):
                wrong.append(f"가정한 조건 {state.get('assumed')} (정답 {item.get('assumed', [])})")
        else:
            wrong.append("판정 없음")
    elif outcome == "give_up":
        if reply.waiting or reply.eligibility or not gave_up:
            wrong.append("판정을 멈추지 않음")
        elif "gave_up" in item and set(gave_up) != set(item["gave_up"]):
            wrong.append(f"판정을 멈춘 조건 {gave_up} (정답 {item['gave_up']})")
    elif outcome == "answered":
        last = item["turns"][-1]["user"]
        if reply.waiting or reply.eligibility or gave_up or state.get("intent") != "info" or state.get("question") != last:
            wrong.append("마지막 말을 새 설명 질문으로 받아 답하지 않음")
    # 위기 신호: 대화 중 처음 잡힌 것 (어느 턴에서든) — 문항 정답 expected_crisis 와 비교
    return {"pass": not wrong, "asks": asks, "wrong": wrong, "crisis_found": next(filter(None, crises), None)}


class ScriptError(Exception):
    """engine 모드 대본(understood)이 모자람 — 그래프가 정답보다 알아듣기를 더 많이 부름."""


def scripted_bot(item: dict, judge_household: Callable) -> "Chatbot":
    """engine 모드용 챗봇 — Claude 대신 문항의 "understood"(정답으로 적어 둔 알아듣기 결과)를 턴마다 돌려준다.

    그래서 engine 모드는 "알아들었다고 치고" 그래프 흐름(되묻기 순서·가정·탈출·중단)과 엔진 판정을 검사한다.
    Claude 가 정말 그렇게 알아듣는지는 chat 모드에서 잰다.
    """
    from app.chat.graph import Deps
    from app.chat.session import Chatbot
    from app.chat.understand import Understanding
    from app.rag.generator import Answer

    script = [
        Understanding(
            intent=t["understood"].get("intent", "eligibility"),
            household=HouseholdInfo(**t["understood"].get("household", {})),
            search_query=t["understood"].get("search_query", t["user"]),
            new_question=t["understood"].get("new_question", False),
        )
        for t in item["turns"]
    ]
    def understand(messages, known, asked):
        if not script:
            raise ScriptError(f"대본 {len(item['turns'])}턴보다 알아듣기를 더 부름 — 흐름이 정답과 다름")
        return script.pop(0)

    deps = Deps(
        understand=understand,
        search=lambda query: [],
        judge=judge_household,
        answer=lambda question, passages, facts, on_text=None: Answer(text="(engine 모드 — 설명 생략)"),
    )
    return Chatbot(deps, log=lambda **_: None)


# ── engine 모드 ─────────────────────────────────────────────


def run_engine(
    items: list[dict],
    judge: Callable[[HouseholdInfo], list[dict]],
    search_pages: Callable[[str], list[int]],
    judge_household: Callable | None = None,
) -> list[dict]:
    """judge: 가구 → 판정 결과 dict 목록 / search_pages: 질문 → 검색된 쪽 목록 (등수 순)
    judge_household: 판정 엔진 입력(Household) → 판정 결과 — multiturn 문항의 챗봇이 쓴다 (없으면 multiturn 은 건너뜀)
    """
    rows = []
    for it in items:
        if it["type"] == "multiturn" and judge_household is None:
            continue
        row = {"id": it["id"], "type": it["type"], "question": it["question"]}
        if it["type"] == "multiturn":  # 위기 감지도 대화의 모든 턴에서 (첫 질문만 보지 않게)
            row |= run_multiturn(it, scripted_bot(it, judge_household), f"engine-{it['id']}")
            rows.append(row | crisis_check(it, row.pop("crisis_found")))
            continue
        if it["type"] == "eligibility":
            row |= compare_judgements(it["expected"], judge(full_household(it)))
        elif it["type"] == "ask":
            got = missing_fields(HouseholdInfo(**it["household"]))
            row |= {"pass": got == it["expected_missing"], "missing": got}
        elif it["type"] == "info":
            pages = search_pages(it["question"])[:TOP_K]
            row |= {"pass": bool(set(pages) & set(it["relevant_pages"])), "pages": pages}
        rows.append(row | crisis_check(it, (c := detect(it["question"])) and c.category))
    return rows


def crisis_check(item: dict, category: str | None) -> dict:
    """위기 감지 채점 — 모든 문항. 정답이 없으면(null) 감지되지 않아야 맞음."""
    expected = item.get("expected_crisis")
    ok = category == expected
    return {"crisis": category, "crisis_ok": ok} | ({"pass": ok} if item["type"] == "crisis" else {})


# ── chat 모드 ───────────────────────────────────────────────


def run_chat(items: list[dict], bot) -> list[dict]:
    """문항마다 새 대화로 챗봇에 질문 하나를 보내 채점한다. bot: app.chat.session.Chatbot"""
    rows = []
    run = uuid.uuid4().hex[:6]
    for it in items:
        thread_id = f"eval-{run}-{it['id']}"  # ai_search_logs 에서 평가 트래픽을 걸러낼 수 있게
        if it["type"] == "multiturn":  # 대화 한 편을 턴마다 보냄 — Claude 가 짧은 답("전세예요")을 제대로 알아듣는지
            row = {"id": it["id"], "type": it["type"], "question": it["question"]} | run_multiturn(it, bot, thread_id)
            rows.append(row | crisis_check(it, row.pop("crisis_found")))  # 턴마다 잡힌 위기 신호
            continue
        reply = bot.send(thread_id, it["question"])
        state = bot.graph.get_state({"configurable": {"thread_id": thread_id}}).values
        row = {"id": it["id"], "type": it["type"], "question": it["question"], "waiting": reply.waiting, "reply": reply.text}

        if it["type"] == "eligibility":
            if reply.waiting:  # 질문에 조건이 다 있는데 되물음 = 알아듣기 실패
                row |= {"pass": False, "programs": len(it["expected"]), "eligible_ok": 0,
                        "wrong": [f"되물음: {state.get('pending_fields')}"]}
            else:
                row |= compare_judgements(it["expected"], reply.eligibility)
            row["household"] = state.get("household")  # Claude 가 알아들은 조건 (틀렸을 때 원인 보기)
        elif it["type"] == "ask":
            got = state.get("pending_fields") if reply.waiting else []
            row |= {"pass": got == it["expected_missing"], "missing": got}
        elif it["type"] == "info":
            cited = sorted({s["page"] for s in reply.sources})
            row |= {
                "pass": bool(set(cited) & set(it["relevant_pages"])),  # 정답 쪽을 인용했나
                "cited_pages": cited,
                # RAGAS 입력: 질문·답변·검색 문맥·참고 답변
                "answer": reply.text,
                "contexts": [p["text"] for p in state.get("passages") or []],
                "reference": it["reference"],
            }
        rows.append(row | crisis_check(it, reply.crisis or None))
    return rows


# ── 요약·출력 ───────────────────────────────────────────────


def summarize(rows: list[dict]) -> dict:
    """유형별 정답률 + 판정 세부 지표."""
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r["pass"])
    summary = {t: {"pass": sum(v), "total": len(v)} for t, v in by_type.items()}

    elig = [r for r in rows if r["type"] == "eligibility"]
    if elig:  # 제도 단위 충족/미충족 정답률 (문항 하나 = 제도 4개)
        summary["eligibility_programs"] = {"pass": sum(r["eligible_ok"] for r in elig), "total": sum(r["programs"] for r in elig)}
    crisis = [r["crisis_ok"] for r in rows]
    summary["crisis_all"] = {"pass": sum(crisis), "total": len(crisis)}  # 오탐 포함 전 문항
    return summary


LABELS = {
    "eligibility": "판정 (문항 단위 — 4개 제도 모두 맞아야 정답)",
    "eligibility_programs": "판정 (제도 단위 충족/미충족)",
    "ask": "되물을 조건",
    "crisis": "위기 감지 (위기 문항)",
    "crisis_all": "위기 감지 (전 문항 — 오탐 포함)",
    "info": "설명 질문",
    "multiturn": "여러 턴 대화 (되묻기·가정·탈출·중단)",
}


def print_report(rows: list[dict], summary: dict, mode: str):
    for r in rows:
        if not r["pass"] or not r["crisis_ok"]:
            detail = r.get("wrong") or r.get("missing") or r.get("pages") or r.get("cited_pages") or ""
            crisis = "" if r["crisis_ok"] else f" [위기 감지 {r['crisis']}]"
            print(f"✗ Q{r['id']:<3}{r['type']:<12}{r['question'][:40]}{crisis}  {detail}")
    info_label = "설명 질문 — 검색 Hit@5" if mode == "engine" else "설명 질문 — 정답 쪽 인용"
    print(f"\n[{mode} 모드] 문항 {len(rows)}개")
    for key, s in summary.items():
        label = info_label if key == "info" else LABELS[key]
        print(f"  {label:<36} {s['pass']:>3} / {s['total']:<3} ({s['pass'] / s['total']:.1%})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="챗봇 평가셋 채점")
    parser.add_argument("--chat", action="store_true", help="챗봇(Claude) 끝까지 실행 — 유료")
    parser.add_argument("--ids", help="일부 문항만 (쉼표로 구분한 id)")
    args = parser.parse_args()
    items = load_items({int(i) for i in args.ids.split(",")} if args.ids else None)

    if args.chat:
        from app.chat.session import Chatbot
        from app.database import create_tables

        create_tables()
        mode, rows = "chat", run_chat(items, Chatbot())
    else:
        from app.config import YEAR
        from app.database import SessionLocal
        from app.rag.retriever import search
        from app.services.eligibility import judge

        with SessionLocal() as db:
            mode, rows = "engine", run_engine(
                items,
                judge=lambda info: [j.model_dump() for j in judge(db, to_household(info), YEAR)],
                search_pages=lambda q: [c.page for c in search(db, q, k=TOP_K)],
                judge_household=lambda household: [j.model_dump() for j in judge(db, household, YEAR)],
            )

    summary = summarize(rows)
    print_report(rows, summary, mode)
    if not args.ids:  # 전체를 돌렸을 때만 저장 (부분 실행이 결과 파일을 덮지 않게)
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"testset_{mode}.json"
        path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"저장: {path.relative_to(EVAL_DIR.parent)}")


if __name__ == "__main__":
    main()
