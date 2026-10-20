"""guide_chunks 테이블 — 지침서 본문 조각(청크) + 임베딩 벡터. (4단계 RAG 검색 대상)

임베딩 = 글의 "의미"를 숫자 1024개로 바꾼 것. 뜻이 비슷한 글은 벡터도 가깝다.
질문도 같은 방식으로 벡터로 바꾼 뒤, 가장 가까운 청크를 찾으면 그게 근거 문단이다.
벡터 칸과 "가까운 순 정렬"은 PostgreSQL 의 pgvector 확장이 제공한다 (docker-compose.yml 의 이미지).

누가 쓰나:
    - ingestion/load_chunks.py   본문 → 청크 → 임베딩 → 이 테이블
    - app/rag/retriever.py       질문과 가까운 청크 검색
"""

from pgvector.sqlalchemy import Vector  # pgvector 의 벡터 칸 타입
from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import EMBEDDING_DIM
from app.database import Base


class GuideChunk(Base):
    """지침서 본문 조각 하나. (테이블: guide_chunks)"""

    __tablename__ = "guide_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int]                                   # 지침서 연도. 예: 2026
    page: Mapped[int]                                   # PDF 쪽번호 (답변 근거 표시용)
    chunk_index: Mapped[int]                            # 그 쪽 안에서 몇 번째 조각인지 (0부터)
    section: Mapped[str]                                # 장 이름. 예: "Ⅲ. 소득조사"
    text: Mapped[str] = mapped_column(Text)             # 조각 본문
    embedding = mapped_column(Vector(EMBEDDING_DIM))    # 임베딩 벡터 (BGE-m3: 1024개 숫자)
