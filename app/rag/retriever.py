"""검색 — 질문과 의미가 가장 가까운 지침서 청크를 찾는다.

    질문 → 임베딩(app/rag/embedding.py) → guide_chunks 에서 코사인 거리가 가까운 순으로 k개

거리 계산과 정렬은 PostgreSQL(pgvector)이 한다. SQL 로 치면:
    SELECT … FROM guide_chunks WHERE year = 2026 ORDER BY embedding <=> :질문벡터 LIMIT 5
    (<=> = pgvector 의 코사인 거리 연산자. 0 = 같은 뜻, 2 = 정반대)
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import YEAR
from app.models import GuideChunk
from app.rag.embedding import embed

TOP_K = 5  # 기본으로 가져올 청크 수


def search(db: Session, question: str, k: int = TOP_K, year: int = YEAR) -> list[GuideChunk]:
    """질문과 가까운 청크 k개 (가까운 순)."""
    query_vector = embed([question])[0]
    return db.scalars(
        select(GuideChunk)
        .where(GuideChunk.year == year)
        .order_by(GuideChunk.embedding.cosine_distance(query_vector))
        .limit(k)
    ).all()
