"""지침서 검색 API — 질문과 관련된 지침서 문단을 찾아 준다. (Claude 호출 없음)

| 메서드 | 경로         | 하는 일                 | 성공 코드 |
|--------|--------------|-------------------------|-----------|
| GET    | /api/search  | 질문으로 지침서 청크 검색 | 200       |

챗봇이 답변 근거로 쓰는 검색(app/rag/retriever.py)과 같다 — 기본 설정: 벡터 검색, 본문만.
UI(frontend/streamlit_app.py)의 "지침서 검색" 탭이 쓴다.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.rag.retriever import search

router = APIRouter(prefix="/api/search", tags=["search"])


class Passage(BaseModel):
    """검색된 지침서 청크 하나."""

    page: int        # PDF 쪽번호
    section: str     # 편·장 (예: "Ⅲ. 소득조사")
    heading: str     # 항목 경로 (예: "4) 근로를 유인하기 위한 요인")
    text: str


@router.get("", response_model=list[Passage])
def search_guide(
    q: str = Query(min_length=1, description="질문", examples=["근로소득 공제"]),
    k: int = Query(default=5, ge=1, le=20, description="가져올 청크 수"),
    db: Session = Depends(get_db),
):
    """질문과 관련 높은 순으로 청크 k개."""
    return [Passage(page=c.page, section=c.section, heading=c.heading, text=c.text) for c in search(db, q, k=k)]
