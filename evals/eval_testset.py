"""챗봇 평가 — 평가셋 50문항(testset_2026.json)으로 판정·되묻기·위기 감지·검색을 채점한다.

두 가지 모드:
    engine (기본, Claude 호출 없음 — 무료)
        eligibility  손계산 정답 가구를 판정 엔진에 직접 넣어 소득인정액·충족 여부가 맞는지
        ask          부분 조건에서 되물을 조건 목록(missing_fields)이 맞는지
        crisis       50문항 전부에 위기 감지 규칙을 돌려 종류가 맞는지 (정답 null = 오탐 검사)
        info         질문으로 검색해 5등 안에 정답 쪽이 나오는지 (Hit@5)
    chat (--chat, Claude 호출 — 유료, 50문항 1회 약 $1 이하 예상)
        질문을 챗봇에 그대로 보내 "Claude 가 조건을 제대로 알아듣고 → 엔진 판정까지 맞게 가는지"를 본다.
        info 문항은 답변·검색 문맥을 저장해 RAGAS 채점(evals/eval_ragas.py, 결제 후 작성)의 입력으로 쓴다.

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


# ── engine 모드 ─────────────────────────────────────────────


def run_engine(items: list[dict], judge: Callable[[HouseholdInfo], list[dict]], search_pages: Callable[[str], list[int]]) -> list[dict]:
    """judge: 가구 → 판정 결과 dict 목록 / search_pages: 질문 → 검색된 쪽 목록 (등수 순)."""
    rows = []
    for it in items:
        row = {"id": it["id"], "type": it["type"], "question": it["question"]}
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
