"""검색 성능 측정 — 평가셋(retrieval_2026.json)의 질문마다 검색해서 정답 쪽이 몇 등에 나오는지 잰다.

지표 (쪽 단위. 정답 쪽 중 하나라도 나오면 정답으로 본다):
    Hit@1  1등이 정답인 질문 비율
    Hit@5  5등 안에 정답이 있는 질문 비율 (LLM 에 넘기는 청크 수 = 5)
    MRR    1 / (처음 정답이 나온 등수) 의 평균. 1등이면 1, 2등이면 0.5, 10등 밖이면 0

사용법 (DB에 청크가 적재돼 있어야 함):
    python -m evals.eval_retrieval                    결과 표 출력
    python -m evals.eval_retrieval --save baseline    evals/results/baseline.json 에도 저장 (전후 비교용)
    python -m evals.eval_retrieval --method vector     검색 방법 지정 (vector / sparse / hybrid, 기본 vector)
"""

import argparse
import json
import sys
from pathlib import Path

from app.database import SessionLocal
from app.rag.retriever import DEFAULT_PARTS, search

PARTS_ALL = ("front", "body", "form", "appendix")

EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = EVAL_DIR / "retrieval_2026.json"
RESULTS_DIR = EVAL_DIR / "results"
MAX_RANK = 10  # 이 등수까지만 본다


def first_hit_rank(pages: list[int], relevant: set[int]) -> int | None:
    """검색된 쪽 목록에서 정답 쪽이 처음 나온 등수 (1부터). 없으면 None."""
    for rank, page in enumerate(pages, start=1):
        if page in relevant:
            return rank
    return None


def summarize(ranks: list[int | None]) -> dict:
    """등수 목록 → Hit@1, Hit@5, MRR."""
    n = len(ranks)
    return {
        "hit@1": sum(1 for r in ranks if r == 1) / n,
        "hit@5": sum(1 for r in ranks if r is not None and r <= 5) / n,
        "mrr": sum(1 / r for r in ranks if r is not None) / n,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="검색 성능 측정")
    parser.add_argument("--save", metavar="LABEL", help="evals/results/LABEL.json 에 결과 저장")
    parser.add_argument("--method", default="vector", choices=["vector", "sparse", "hybrid"])
    parser.add_argument("--all-parts", action="store_true", help="서식·부록·목차까지 검색 (기본은 본문만)")
    args = parser.parse_args()

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]
    rows = []
    with SessionLocal() as db:
        for q in questions:
            pages = [c.page for c in search(db, q["question"], k=MAX_RANK, method=args.method, parts=PARTS_ALL if args.all_parts else DEFAULT_PARTS)]
            rank = first_hit_rank(pages, set(q["relevant_pages"]))
            rows.append({"id": q["id"], "question": q["question"], "rank": rank, "pages": pages})

    for row in rows:
        mark = "✗" if row["rank"] is None else f"{row['rank']:>2}"
        print(f"{mark}  Q{row['id']:<3}{row['question']}  → {row['pages'][:5]}")

    metrics = summarize([row["rank"] for row in rows])
    print(f"\n질문 {len(rows)}개  Hit@1 {metrics['hit@1']:.1%}  Hit@5 {metrics['hit@5']:.1%}  MRR {metrics['mrr']:.3f}")

    if args.save:
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"{args.save}.json"
        path.write_text(json.dumps({"method": args.method, "all_parts": args.all_parts, "metrics": metrics, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"저장: {path.relative_to(EVAL_DIR.parent)}")


if __name__ == "__main__":
    main()
