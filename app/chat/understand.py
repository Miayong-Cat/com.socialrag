"""질문 이해 — 사용자의 말에서 의도·가구 조건·검색어를 한 번에 뽑는다. (Claude 구조화 출력)

Claude 에게 정해진 형식(Understanding)으로만 답하게 해서, 결과를 그대로 파이썬 객체로 받는다.
    intent        "eligibility" = 내가 받을 수 있는지 묻는 질문 / "info" = 제도·절차 설명 질문
    household     이번 말에 새로 나온 가구 조건만 (말하지 않은 칸은 null)
    search_query  지침서에서 근거를 찾기 좋은 문장 — 일상어를 지침서 용어로 바꿔 쓴다
                  예) "일해서 번 돈은 얼마나 빼주나요?" → "생계급여 근로소득 공제 기준"
                  (5단계 평가에서 일상어 질문이 검색에 실패하던 문제의 대책)

숫자 계산은 시키지 않는다 — 금액을 원 단위로 옮겨 적는 것까지만. 판정은 판정 엔진이 한다.
"""

import json
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.chat.state import HouseholdInfo
from app.config import LLM_MODEL

SYSTEM_PROMPT = """\
당신은 국민기초생활보장 상담 챗봇의 "질문 이해" 단계입니다. 사용자의 마지막 말을 읽고 정해진 형식으로만 답합니다.

- intent: 사용자가 자기(또는 가족) 가구가 급여를 받을 수 있는지 알고 싶어 하면 "eligibility", 제도·절차·기준 자체를 묻는 질문이면 "info".
- household: 마지막 말에 새로 나온 가구 조건만 채우고, 나오지 않은 칸은 null 로 두세요. 추측해서 채우지 마세요.
  - 금액은 원 단위 정수로 옮기세요. 예) "월 150만원" → 1500000, "보증금 5천" → 50000000
  - "재산 없어요"처럼 재산이 전혀 없다고 하면 재산 칸(housing, general, financial, car_full_rate, debt)을 모두 0 으로.
  - "소득 없어요"이면 earned_income 을 0 으로.
- search_query: 지침서에서 근거 문단을 찾기 위한 한 문장. 일상어를 지침서 용어로 바꾸세요.
  예) "일해서 번 돈" → "근로소득", "빼주나요" → "공제", "장례비" → "장제급여", "아이 낳으면" → "해산급여"
"""


class Understanding(BaseModel):
    """질문 이해 결과 (Claude 가 이 형식으로만 답함)."""

    intent: Literal["eligibility", "info"]
    household: HouseholdInfo
    search_query: str = Field(description="지침서 검색용 문장 (지침서 용어로)")


def understand(messages: list[dict], known: HouseholdInfo, asked: list[str], client=None) -> Understanding:
    """대화 기록 → Understanding.

    messages: 지금까지의 대화 (마지막이 사용자의 말)
    known:    이미 모은 가구 조건 — 사용자가 "그대로예요" 같은 말을 해도 맥락을 알도록 같이 보여 줌
    asked:    방금 되물은 조건 이름 (예: ["region", "assets"]) — 짧은 답("서울이요")을 해석하는 단서
    client:   테스트에서 가짜를 넣는다. 없으면 새로 만든다.
    """
    client = client or anthropic.Anthropic()
    context = (
        f"[이미 아는 가구 조건] {json.dumps(known.model_dump(exclude_none=True), ensure_ascii=False)}\n"
        f"[방금 물어본 조건] {', '.join(asked) if asked else '없음'}"
    )
    recent = messages[-10:]  # 최근 대화만 (오래된 대화는 조건이 이미 household 에 들어 있음)
    response = client.beta.messages.parse(
        model=LLM_MODEL,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},  # 정해진 형식으로 옮겨 적는 일이라 low 로 충분
        system=SYSTEM_PROMPT,
        # 첫 user 메시지에 맥락을 붙여 보낸다 (system 은 고정해 두어 캐시가 깨지지 않게)
        messages=[{"role": "user", "content": context}, *recent],
        output_format=Understanding,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        # 거절되면 조건 없이 원래 질문으로 검색만 한다
        return Understanding(intent="info", household=HouseholdInfo(), search_query=messages[-1]["content"])
    return response.parsed_output
