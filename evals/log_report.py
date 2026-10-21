"""ai_search_logs 집계 리포트 — 챗봇이 실제로 어떻게 쓰이고 얼마나 빠르고 얼마나 판정에 성공하는지.

볼 수 있는 것:
    응답 시간      전체·의도별·턴 종류별 평균 / 중간값 / p95 (느린 꼬리가 어디인지)
    판정 성공률    판정 질문으로 시작한 대화 중 실제로 판정까지 간 비율, 한 번에 판정한 비율, 평균 되묻기 횟수
    되묻기         되물은 턴 수, 많이 부족했던 조건 수
    판정 결과      제도별 충족 비율
    위기 신호      종류별 건수
    검색           답변 턴의 평균 검색 청크 수

평가 실행(thread_id 가 "eval-" 로 시작, evals/eval_testset.py --chat)은 기본으로 뺀다.

사용법 (DB 실행 필요):
    python -m evals.log_report                    사용자 대화만
    python -m evals.log_report --eval             평가 실행만
    python -m evals.log_report --eval --run dfd852   평가 실행 한 번만 (thread_id 가 eval-dfd852-…)
    python -m evals.log_report --days 7           최근 7일
    python -m evals.log_report --save weekly      evals/results/log_report_weekly.md 에도 저장
"""

import argparse
import math
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

EVAL_PREFIX = "eval-"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass
class Turn:
    """로그 한 줄에서 집계에 쓰는 칸만 (app/models/ai_search_log.py)."""

    id: int
    created_at: datetime
    thread_id: str
    intent: str | None
    crisis: str | None
    retrieved_doc_count: int
    response_time_ms: int
    waiting: bool
    missing_fields_count: int
    eligibility_result: dict | None
    error: str | None = None  # 실패한 턴이면 오류 (성공이면 None)


def percentile(values: list[int], p: float) -> int:
    """nearest-rank 백분위 (p=95 → 95% 의 값이 이 값 이하)."""
    ordered = sorted(values)
    return ordered[max(math.ceil(p / 100 * len(ordered)) - 1, 0)]


def latency(values: list[int]) -> dict:
    return {
        "count": len(values),
        "mean": round(statistics.mean(values)),
        "median": round(statistics.median(values)),
        "p95": percentile(values, 95),
        "max": max(values),
    }


def turn_kind(t: Turn) -> str:
    """턴 종류 — 응답 시간이 하는 일에 따라 크게 다르므로 나눠서 본다."""
    if t.error:
        return "실패"              # 오류로 답하지 못함 (Claude 오류·연결 끊김 등)
    if t.crisis == "suicide":
        return "위기 중단"         # 규칙만 — Claude 호출 없음
    if t.waiting:
        return "되묻기"            # 알아듣기(Claude 1회)만
    if t.eligibility_result:
        return "판정 + 답변"       # 알아듣기 + 판정 + 검색 + 답변
    return "설명 답변"             # 알아듣기 + 검색 + 답변


def conversations(turns: list[Turn]) -> list[list[Turn]]:
    """thread_id 별로 묶고 시간순 정렬."""
    by_thread = defaultdict(list)
    for t in turns:
        by_thread[t.thread_id].append(t)
    return [sorted(ts, key=lambda t: (t.created_at, t.id)) for ts in by_thread.values()]


def judgement_funnel(convs: list[list[Turn]]) -> dict:
    """판정 질문으로 시작한 '판정 시도'가 판정까지 갔는지.

    한 대화에 판정 질문이 여러 번 있을 수 있어서, 시도 = 판정 의도 턴부터 판정이 나오거나(성공)
    다른 의도의 새 질문이 오거나 대화가 끝날 때까지(실패 — 되묻기 중 이탈 등).
    """
    attempts, succeeded, first_turn, asks = 0, 0, 0, []
    for turns in convs:
        current = None  # 진행 중인 시도의 되묻기 횟수
        for t in turns:
            if t.crisis == "suicide":
                continue  # 위기 중단 턴은 시도에 넣지도 빼지도 않음
            if current is None and t.intent == "eligibility":
                attempts, current = attempts + 1, 0
            if current is None:
                continue
            if t.waiting:
                current += 1
            elif t.eligibility_result:
                succeeded += 1
                first_turn += current == 0
                asks.append(current)
                current = None
            else:
                current = None  # 판정 없이 답이 나감 (다른 질문으로 넘어감)
    return {
        "attempts": attempts,
        "succeeded": succeeded,
        "first_turn": first_turn,               # 되묻기 없이 첫 턴에 판정
        "avg_asks": round(statistics.mean(asks), 2) if asks else 0,  # 성공한 시도의 평균 되묻기 횟수
    }


def build_report(turns: list[Turn]) -> dict:
    """집계 결과 (숫자만). 출력 모양은 render() 가 정한다."""
    if not turns:
        return {"turns": 0}
    convs = conversations(turns)
    by_kind = defaultdict(list)
    for t in turns:
        by_kind[turn_kind(t)].append(t.response_time_ms)

    program_total, program_ok = Counter(), Counter()
    for t in turns:
        for program, eligible in (t.eligibility_result or {}).items():
            program_total[program] += 1
            program_ok[program] += bool(eligible)

    answered = [t for t in turns if not t.waiting and t.crisis != "suicide" and not t.error]
    asked = [t for t in turns if t.waiting]
    return {
        "turns": len(turns),
        "conversations": len(convs),
        "period": (min(t.created_at for t in turns), max(t.created_at for t in turns)),
        "intent": Counter(t.intent or ("(실패)" if t.error else "(위기 중단)") for t in turns),
        "failed": sum(bool(t.error) for t in turns),
        "latency_all": latency([t.response_time_ms for t in turns]),
        "latency_by_kind": {k: latency(v) for k, v in sorted(by_kind.items())},
        "funnel": judgement_funnel(convs),
        "asked_turns": len(asked),
        "missing_fields": Counter(t.missing_fields_count for t in asked),
        "programs": {p: (program_ok[p], program_total[p]) for p in program_total},
        "crisis": Counter(t.crisis for t in turns if t.crisis),
        "avg_docs": round(statistics.mean(t.retrieved_doc_count for t in answered), 2) if answered else 0,
    }


def pct(a: int, b: int) -> str:
    return f"{a / b:.1%}" if b else "-"


def render(r: dict, title: str) -> str:
    """집계 결과 → 마크다운."""
    if not r["turns"]:
        return f"# {title}\n\n기록이 없습니다.\n"
    start, end = r["period"]
    f = r["funnel"]
    lines = [
        f"# {title}",
        "",
        f"- 기간: {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M} (DB 시각 = UTC, 한국 시각 −9시간)",
        f"- 대화 {r['conversations']}개 · 턴 {r['turns']}개 · 의도 "
        + ", ".join(f"{k} {v}" for k, v in r["intent"].most_common()),
        f"- 실패한 턴: {r['failed']} ({pct(r['failed'], r['turns'])})",
        "",
        "## 응답 시간 (ms)",
        "",
        "| 턴 종류 | 턴 수 | 평균 | 중간값 | p95 | 최대 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    rows = [("전체", r["latency_all"]), *r["latency_by_kind"].items()]
    lines += [f"| {k} | {v['count']} | {v['mean']:,} | {v['median']:,} | {v['p95']:,} | {v['max']:,} |" for k, v in rows]
    lines += [
        "",
        "## 판정 성공률",
        "",
        "| 지표 | 값 |",
        "|---|---|",
        f"| 판정 시도 (판정 질문으로 시작) | {f['attempts']} |",
        f"| 판정까지 감 | {f['succeeded']} ({pct(f['succeeded'], f['attempts'])}) |",
        f"| 되묻기 없이 첫 턴에 판정 | {f['first_turn']} ({pct(f['first_turn'], f['attempts'])}) |",
        f"| 판정까지 평균 되묻기 횟수 | {f['avg_asks']} |",
        f"| 되묻기 턴 (부족한 조건 수별) | {r['asked_turns']} — "
        + (", ".join(f"{n}개 {c}" for n, c in sorted(r["missing_fields"].items())) or "-") + " |",
    ]
    if r["programs"]:
        lines += ["", "## 판정 결과 — 제도별 충족 비율", "", "| 제도 | 충족 / 판정 |", "|---|---|"]
        lines += [f"| {p} | {ok} / {n} ({pct(ok, n)}) |" for p, (ok, n) in r["programs"].items()]
    lines += [
        "",
        "## 기타",
        "",
        "- 위기 신호: " + (", ".join(f"{k} {v}" for k, v in r["crisis"].most_common()) or "없음"),
        f"- 답변 턴 평균 검색 청크 수: {r['avg_docs']}",
    ]
    return "\n".join(lines) + "\n"


def load_turns(eval_only: bool, days: int | None, run: str | None = None) -> list[Turn]:
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import AiSearchLog

    query = select(AiSearchLog)
    is_eval = AiSearchLog.thread_id.startswith(EVAL_PREFIX)
    query = query.where(is_eval if eval_only else ~is_eval)
    if run:  # 평가 실행 번호 (evals/eval_testset.py 가 thread_id 에 넣음) — 부분 실행이 섞이지 않게
        query = query.where(AiSearchLog.thread_id.startswith(f"{EVAL_PREFIX}{run}-"))
    if days:
        # created_at 은 DB 의 now()(UTC) 로 찍히므로 비교도 DB 시각으로 한다 (PC 시각과 9시간 차이)
        query = query.where(AiSearchLog.created_at >= func.now() - timedelta(days=days))
    with SessionLocal() as db:
        return [
            Turn(**{f: getattr(row, f) for f in Turn.__dataclass_fields__})
            for row in db.scalars(query).all()
        ]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ai_search_logs 집계 리포트")
    parser.add_argument("--eval", action="store_true", help="평가 실행(eval-*) 기록만 집계")
    parser.add_argument("--run", help="평가 실행 번호 하나만 (--eval 과 함께, thread_id 의 eval-<번호>-)")
    parser.add_argument("--days", type=int, help="최근 N일만")
    parser.add_argument("--save", metavar="LABEL", help="evals/results/log_report_LABEL.md 에 저장")
    args = parser.parse_args()

    if args.run and not args.eval:
        parser.error("--run 은 --eval 과 함께 씁니다")
    title = "챗봇 로그 리포트 — " + ("평가 실행" if args.eval else "사용자 대화") + (f" {args.run}" if args.run else "") + (f" (최근 {args.days}일)" if args.days else "")
    text = render(build_report(load_turns(args.eval, args.days, args.run)), title)
    print(text)
    if args.save:
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"log_report_{args.save}.md"
        path.write_text(text, encoding="utf-8")
        print(f"저장: {path}")


if __name__ == "__main__":
    main()
