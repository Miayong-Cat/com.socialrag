"""챗봇 API — 메시지를 보내면 챗봇이 답한다. 조건이 부족하면 되묻는다.

| 메서드 | 경로       | 하는 일          | 성공 코드 |
|--------|------------|------------------|-----------|
| POST   | /api/chat  | 메시지 보내기    | 200       |

대화 이어 가기:
    첫 요청은 thread_id 없이 보낸다 → 응답의 thread_id 를 다음 요청에 그대로 넣는다.
    같은 thread_id 면 앞에서 말한 가구 조건이 이어지고, 되묻는 중(waiting=true)이면 메시지가 그 답이 된다.

주의: 대화 상태는 서버 메모리에 있다 (InMemorySaver). 서버를 다시 켜면 대화가 사라진다.
"""

import uuid
from functools import lru_cache

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.chat.session import Chatbot

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """챗봇에 보내는 메시지."""

    thread_id: str | None = Field(default=None, description="이어 갈 대화 번호. 첫 메시지는 비워 둔다")
    message: str = Field(min_length=1, examples=["혼자 사는데 생계급여 받을 수 있나요?"])


class ChatResponse(BaseModel):
    """챗봇의 답."""

    thread_id: str              # 다음 요청에 넣을 대화 번호
    reply: str                  # 챗봇의 답 (되묻는 중이면 질문)
    waiting: bool               # true = 조건을 되묻는 중
    eligibility: list[dict]     # 이번에 판정했으면 제도별 결과 (app/schemas.py 의 ProgramJudgement 모양)
    sources: list[dict]         # 답변 근거 {page, section, quote}


@lru_cache(maxsize=1)  # 서버 전체에서 챗봇 하나 (대화 상태를 같이 보관해야 하므로)
def get_chatbot() -> Chatbot:
    """챗봇. 테스트에서는 app.dependency_overrides 로 가짜 챗봇을 끼운다."""
    return Chatbot()


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, bot: Chatbot = Depends(get_chatbot)):
    """메시지 하나를 처리해 챗봇의 답을 돌려준다."""
    thread_id = request.thread_id or uuid.uuid4().hex
    try:
        reply = bot.send(thread_id, request.message)
    except anthropic.AuthenticationError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Claude API 키가 없거나 잘못됐습니다 (.env 의 ANTHROPIC_API_KEY)") from e
    except LookupError as e:  # 기준 중위소득 미적재 등 (app/services/eligibility.py)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return ChatResponse(
        thread_id=thread_id,
        reply=reply.text,
        waiting=reply.waiting,
        eligibility=reply.eligibility,
        sources=reply.sources,
    )
