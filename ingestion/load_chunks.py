"""[적재 4/4] 지침서 본문 → 청크 → 임베딩 → DB (guide_chunks 테이블). 4단계 RAG 검색의 재료.

extract_text.py 가 만든 쪽별 본문을 청크로 자르고(app/rag/chunking.py),
청크마다 BGE-m3 임베딩(dense + sparse)을 계산해(app/rag/embedding.py) DB에 넣는다.
같은 연도로 여러 번 실행해도 중복이 생기지 않는다 (그 연도 청크를 지우고 새로 넣음).
--recreate: 테이블을 지우고 새로 만든다. 칸(컬럼)이 바뀌었을 때 사용 — 다른 연도 청크도 지워진다.

사용법:
    python -m ingestion.load_chunks
    python -m ingestion.load_chunks --recreate     guide_chunks 테이블 구조가 바뀐 뒤
    python -m ingestion.load_chunks --chunking size   글자 수 청킹 (기본은 structure — 비교 실험용)
읽는 파일:
    data/processed/text_2026.jsonl   (app/config.py 의 TEXT_JSONL_PATH)
저장 위치:
    app/config.py 의 DATABASE_URL (Docker로 띄운 PostgreSQL — 먼저 docker compose up -d)
걸리는 시간:
    처음 한 번은 모델 다운로드(약 2.3GB). 임베딩은 CPU로 청크 약 1,000개에 20~30분
    (BGE-m3 는 5억 6천만 파라미터 모델이라 CPU에서는 글 하나에 1초 남짓 걸림).
"""

import argparse
import json
import sys

from pgvector import SparseVector
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import SPARSE_DIM, TEXT_JSONL_PATH, YEAR
from app.database import SessionLocal, create_tables, engine
from app.models import GuideChunk
from app.rag.chunking import Chunk, build_chunks
from app.rag.embedding import embed_with_sparse


def load(
    db: Session, chunks: list[Chunk], dense: list[list[float]], sparse: list[dict[int, float]], year: int
) -> None:
    """청크와 벡터를 guide_chunks 테이블에 넣고 commit 한다. 그 연도의 기존 청크는 먼저 지운다."""
    db.execute(delete(GuideChunk).where(GuideChunk.year == year))
    for chunk, vector, weights in zip(chunks, dense, sparse, strict=True):  # strict → 개수가 다르면 에러
        db.add(
            GuideChunk(
                year=year,
                page=chunk.page,
                chunk_index=chunk.index,
                section=chunk.section,
                part=chunk.part,
                heading=chunk.heading,
                text=chunk.text,
                embedding=vector,
                sparse=SparseVector(weights, SPARSE_DIM),
            )
        )
    db.commit()


def main():
    """본문 읽기 → 청킹 → 임베딩 → 적재."""
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 터미널 한글 깨짐 방지
    parser = argparse.ArgumentParser(description="지침서 청크 적재")
    parser.add_argument("--recreate", action="store_true", help="guide_chunks 테이블을 지우고 새로 만듦")
    parser.add_argument("--chunking", default="structure", choices=["structure", "size"], help="청킹 방법")
    args = parser.parse_args()
    with TEXT_JSONL_PATH.open(encoding="utf-8") as f:
        pages = [json.loads(line) for line in f]

    chunks = build_chunks(pages, strategy=args.chunking)
    print(f"청크 {len(chunks)}개 ({args.chunking} 청킹, 본문 {len(pages)}쪽) — 임베딩 계산 중…")
    # 헤더("[장 이름] p.쪽")를 붙인 글로 임베딩한다 → 검색할 때 장 이름도 같이 반영됨
    dense, sparse = embed_with_sparse([c.embedding_text() for c in chunks])

    if args.recreate:
        GuideChunk.__table__.drop(engine, checkfirst=True)  # create_all 은 있는 테이블의 칸을 바꾸지 못하므로
    create_tables()
    with SessionLocal() as db:
        load(db, chunks, dense, sparse, YEAR)
    print(f"적재 완료: guide_chunks {len(chunks)}건 ({YEAR}년)")


if __name__ == "__main__":
    main()
