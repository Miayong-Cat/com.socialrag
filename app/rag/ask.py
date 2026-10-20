"""질문 하나를 터미널에서 바로 해 보는 CLI — 검색 → 답변 생성을 한 번에 실행한다.

사용법:
    python -m app.rag.ask "생계급여 근로소득 공제는 어떻게 되나요?"
    python -m app.rag.ask "…" --search-only      LLM 없이 검색 결과만 보기 (API 키 불필요)

필요한 것:
    - DB에 청크가 적재돼 있어야 함 (python -m ingestion.load_chunks)
    - 답변 생성까지 하려면 .env 에 ANTHROPIC_API_KEY
"""

import argparse
import sys

from app.database import SessionLocal
from app.rag.generator import generate
from app.rag.retriever import TOP_K, search


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 터미널 한글 깨짐 방지
    parser = argparse.ArgumentParser(description="지침서 RAG 질문")
    parser.add_argument("question", help="질문")
    parser.add_argument("-k", type=int, default=TOP_K, help=f"가져올 청크 수 (기본 {TOP_K})")
    parser.add_argument("--search-only", action="store_true", help="검색 결과만 보고 답변은 만들지 않음")
    args = parser.parse_args()

    with SessionLocal() as db:
        chunks = search(db, args.question, k=args.k)

    print("── 검색된 지침서 문단 ──")
    for i, chunk in enumerate(chunks, start=1):
        preview = chunk.text[:80].replace("\n", " ")
        print(f"{i}. [{chunk.section}] p.{chunk.page}  {preview}…")
    if args.search_only:
        return

    answer = generate(args.question, chunks)
    print("\n── 답변 ──")
    print(answer.text)
    print("\n── 근거 ──")
    for source in answer.sources:
        print(f"p.{source.page} [{source.section}] “{source.quote}”")


if __name__ == "__main__":
    main()
