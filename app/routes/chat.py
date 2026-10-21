"""챗봇 API — 메시지를 보내면 챗봇이 답한다. 조건이 부족하면 되묻는다.

| 메서드 | 경로             | 하는 일                               | 성공 코드 |
|--------|------------------|---------------------------------------|-----------|
| POST   | /api/chat        | 메시지 보내기                         | 200       |
| POST   | /api/chat/stream | 메시지 보내기 (답을 써지는 대로 받기) | 200       |

대화 이어 가기:
    첫 요청은 thread_id 없이 보낸다 → 응답의 thread_id 를 다음 요청에 그대로 넣는다.
    같은 thread_id 면 앞에서 말한 가구 조건이 이어지고, 되묻는 중(waiting=true)이면 메시지가 그 답이 된다.

스트리밍 (/api/chat/stream): 한 줄에 JSON 하나씩(NDJSON) 보낸다.
    {"type": "delta", "text": "…"}        답의 글 조각 (미리 보기용, 여러 번)
    {"type": "done", ...ChatResponse}     완성된 답 (마지막에 한 번) — 화면은 이걸로 바꿔 보여 준다
    {"type": "error", "message": "…"}     실패 (응답 코드는 이미 200 으로 나갔으므로 줄로 알린다)

주의: 대화 상태는 서버 메모리에 있다 (InMemorySaver). 서버를 다시 켜면 대화가 사라진다.
"""

import json
import logging
import uuid
from collections.abc import Iterator
from functools import lru_cache

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.chat.session import Chatbot, Reply

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


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


KEY_ERROR = "Claude API 키가 없거나 잘못됐습니다 (.env 의 ANTHROPIC_API_KEY)"


def claude_error(e: anthropic.APIError) -> str:
    """Claude API 오류 → 화면에 보여 줄 문장. 키 오류 외에도 크레딧 부족(400)·과부하(529)·연결 실패가 있다."""
    if isinstance(e, anthropic.AuthenticationError):
        return KEY_ERROR
    status_code = getattr(e, "status_code", None)
    return f"지금은 AI 상담을 할 수 없습니다 (Claude API 오류{f' {status_code}' if status_code else ''}: {e.message})"


def to_response(thread_id: str, reply: Reply) -> ChatResponse:
    return ChatResponse(
        thread_id=thread_id,
        reply=reply.text,
        waiting=reply.waiting,
        eligibility=reply.eligibility,
        sources=reply.sources,
    )


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, bot: Chatbot = Depends(get_chatbot)):
    """메시지 하나를 처리해 챗봇의 답을 돌려준다."""
    thread_id = request.thread_id or uuid.uuid4().hex
    try:
        reply = bot.send(thread_id, request.message)
    except anthropic.APIError as e:  # 키 오류·크레딧 부족·연결 실패 등 — 500 대신 이유를 알린다
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, claude_error(e)) from e
    except LookupError as e:  # 기준 중위소득 미적재 등 (app/services/eligibility.py)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return to_response(thread_id, reply)


@router.post("/stream")
def chat_stream(request: ChatRequest, bot: Chatbot = Depends(get_chatbot)):
    """메시지 하나를 처리하며 답을 써지는 대로 보낸다 (NDJSON — 맨 위 설명 참고)."""
    thread_id = request.thread_id or uuid.uuid4().hex

    def line(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    def events() -> Iterator[str]:
        try:
            for item in bot.stream(thread_id, request.message):
                if isinstance(item, Reply):
                    yield line({"type": "done"} | to_response(thread_id, item).model_dump())
                else:
                    yield line({"type": "delta", "text": item})
        except anthropic.APIError as e:
            yield line({"type": "error", "message": claude_error(e)})
        except LookupError as e:
            yield line({"type": "error", "message": str(e)})
        except Exception:  # noqa: BLE001 — 응답 코드(200)가 이미 나갔으므로 그냥 끊지 말고 error 줄로 알린다
            logger.exception("챗봇 스트리밍 실패 (thread_id=%s)", thread_id)
            yield line({"type": "error", "message": "알 수 없는 오류로 답하지 못했습니다. 잠시 후 다시 시도해 주세요."})

    return StreamingResponse(events(), media_type="application/x-ndjson")
