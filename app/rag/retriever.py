"""검색 — 질문과 관련된 지침서 청크를 찾는다.

질문도 청크와 같은 방식으로 BGE-m3 임베딩(dense + sparse)을 만든 뒤 비교한다 (app/rag/embedding.py).

검색 방법 (method):
    "vector"  dense 코사인 유사도 순 — 뜻이 비슷한 글 (말투가 달라도 잡힘) (기본값)
    "sparse"  sparse 내적 순 — 질문의 핵심 낱말이 들어 있는 글 (정확한 용어 일치)
    "hybrid"  dense 유사도 + SPARSE_WEIGHT × sparse 점수
    기본값은 "vector" — 평가셋에서 hybrid 가 vector 보다 낫지 않았다 (evals/README.md)

계산·정렬은 모두 PostgreSQL(pgvector)이 한 번의 SQL 로 한다. hybrid 를 SQL 로 치면:
    SELECT … FROM guide_chunks
    WHERE year = 2026 AND part IN ('body')
    ORDER BY (1 - (embedding <=> :dense)) + 0.3 * (-(sparse <#> :sparse)) DESC
    LIMIT 5
    (<=> = 코사인 거리, <#> = 내적에 마이너스를 붙인 값 — pgvector 연산자. 그래서 1 − 와 − 를 붙여 "클수록 가까움"으로 바꿈)
청크가 1천 개 안팎이라 색인 없이 전부 계산해도 충분히 빠르다.

검색 대상 구분 (parts): 기본은 본문("body")만. 서식·부록·목차는 요약표나 양식이라
    질문과 낱말은 겹치지만 답은 없는 경우가 많다 (app/rag/chunking.py 의 PARTS).
"""

from pgvector import SparseVector
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SPARSE_DIM, YEAR
from app.models import GuideChunk
from app.rag.embedding import embed_with_sparse

TOP_K = 5                  # 기본으로 가져올 청크 수
SPARSE_WEIGHT = 0.3        # hybrid 에서 sparse 점수 비중 (BGE-m3 논문의 dense 1 : sparse 0.3)
DEFAULT_PARTS = ("body",)  # 기본 검색 대상 구분


def search(
    db: Session,
    question: str,
    k: int = TOP_K,
    year: int = YEAR,
    method: str = "vector",
    parts: tuple[str, ...] = DEFAULT_PARTS,
) -> list[GuideChunk]:
    """질문과 관련된 청크 k개 (관련 높은 순)."""
    [dense], [weights] = embed_with_sparse([question])
    dense_score = 1 - GuideChunk.embedding.cosine_distance(dense)
    sparse_score = -GuideChunk.sparse.max_inner_product(SparseVector(weights, SPARSE_DIM))

    if method == "vector":
        score = dense_score
    elif method == "sparse":
        score = sparse_score
    elif method == "hybrid":
        score = dense_score + SPARSE_WEIGHT * sparse_score
    else:
        raise ValueError(f"알 수 없는 검색 방법: {method}")

    return db.scalars(
        select(GuideChunk)
        .where(GuideChunk.year == year, GuideChunk.part.in_(parts))
        .order_by(score.desc())
        .limit(k)
    ).all()
