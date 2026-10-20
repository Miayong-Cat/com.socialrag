"""[적재 4/4] 지침서 본문 → 청크 → 임베딩 → DB (guide_chunks 테이블). 4단계 RAG 검색의 재료.

extract_text.py 가 만든 쪽별 본문을 청크로 자르고(app/rag/chunking.py),
청크마다 BGE-m3 임베딩을 계산해(app/rag/embedding.py) DB에 넣는다.
같은 연도로 여러 번 실행해도 중복이 생기지 않는다 (그 연도 청크를 지우고 새로 넣음).

사용법:
    python -m ingestion.load_chunks
읽는 파일:
    data/processed/text_2026.jsonl   (app/config.py 의 TEXT_JSONL_PATH)
저장 위치:
    app/config.py 의 DATABASE_URL (Docker로 띄운 PostgreSQL — 먼저 docker compose up -d)
걸리는 시간:
    처음 한 번은 모델 다운로드(약 2.3GB). 임베딩은 CPU로 청크 약 870개에 수 분~십여 분.
"""

import json
import sys

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import TEXT_JSONL_PATH, YEAR
from app.database import SessionLocal, create_tables
from app.models import GuideChunk
from app.rag.chunking import Chunk, build_chunks
from app.rag.embedding import embed


def load(db: Session, chunks: list[Chunk], vectors: list[list[float]], year: int) -> None:
    """청크와 벡터를 guide_chunks 테이블에 넣고 commit 한다. 그 연도의 기존 청크는 먼저 지운다."""
    db.execute(delete(GuideChunk).where(GuideChunk.year == year))
    for chunk, vector in zip(chunks, vectors, strict=True):  # strict → 개수가 다르면 에러
        db.add(
            GuideChunk(
                year=year,
                page=chunk.page,
                chunk_index=chunk.index,
                section=chunk.section,
                text=chunk.text,
                embedding=vector,
            )
        )
    db.commit()


def main():
    """본문 읽기 → 청킹 → 임베딩 → 적재."""
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 터미널 한글 깨짐 방지
    with TEXT_JSONL_PATH.open(encoding="utf-8") as f:
        pages = [json.loads(line) for line in f]

    chunks = build_chunks(pages)
    print(f"청크 {len(chunks)}개 (본문 {len(pages)}쪽) — 임베딩 계산 중…")
    # 헤더("[장 이름] p.쪽")를 붙인 글로 임베딩한다 → 검색할 때 장 이름도 같이 반영됨
    vectors = embed([c.embedding_text() for c in chunks])

    create_tables()
    with SessionLocal() as db:
        load(db, chunks, vectors, YEAR)
    print(f"적재 완료: guide_chunks {len(chunks)}건 ({YEAR}년)")


if __name__ == "__main__":
    main()
