"""ai_search_logs 테이블 — 챗봇 대화 한 턴 = 한 줄. 응답 시간·판정 결과 등을 쌓아 나중에 집계한다.

쌓아 두면 이런 질문에 감이 아니라 숫자로 답할 수 있다:
    - 평균 응답 시간은? 어느 의도(판정/설명)가 느린가?
    - 판정 질문 중 조건이 부족해 되물은 비율은? 몇 개가 부족했나?
    - 위기 신호는 얼마나 자주 감지되나?

누가 쓰나:
    - app/services/search_log.py   한 턴이 끝날 때마다 기록 (app/chat/session.py 에서 부름)
"""

from datetime import datetime

from sqlalchemy import JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AiSearchLog(Base):
    """챗봇 대화 한 턴의 기록. (테이블: ai_search_logs)"""

    __tablename__ = "ai_search_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())  # 기록 시각 (DB가 채움)
    thread_id: Mapped[str]                              # 대화 번호 — 같은 대화의 턴끼리 묶어 볼 때
    question: Mapped[str] = mapped_column(Text)         # 사용자가 이번 턴에 보낸 메시지
    intent: Mapped[str | None]                          # "eligibility" / "info" (위기 중단이면 None)
    crisis: Mapped[str | None]                          # 위기 신호 종류 (없으면 None)
    retrieved_doc_count: Mapped[int]                    # 검색한 지침서 청크 수 (검색 안 했으면 0)
    response_time_ms: Mapped[int]                       # 응답까지 걸린 시간 (밀리초)
    waiting: Mapped[bool]                               # True = 이번 답이 조건 되묻기
    missing_fields_count: Mapped[int]                   # 부족해서 되물은 조건 수
    # 판정 요약 {"생계급여": true, …}. none_as_null → 판정 안 했으면 JSON 의 null 이 아니라 SQL NULL
    eligibility_result: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
