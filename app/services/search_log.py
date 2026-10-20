"""검색·판정 로그 기록 — 챗봇 한 턴이 끝날 때마다 ai_search_logs 테이블에 한 줄 넣는다.

로그 기록이 실패해도(DB 꺼짐 등) 대화는 계속돼야 하므로, 에러는 경고로만 남기고 넘어간다.
"""

import logging

from app.database import SessionLocal
from app.models import AiSearchLog

logger = logging.getLogger(__name__)


def record(**fields) -> None:
    """한 턴 기록. fields 는 AiSearchLog 의 칸 이름 그대로 (app/models/ai_search_log.py)."""
    try:
        with SessionLocal() as db:
            db.add(AiSearchLog(**fields))
            db.commit()
    except Exception:  # noqa: BLE001 — 어떤 이유로든 로그 실패가 대화를 막으면 안 됨
        logger.warning("ai_search_logs 기록 실패", exc_info=True)
