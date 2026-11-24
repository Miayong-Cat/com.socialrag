"""질문 이해 — 사용자의 말에서 의도·가구 조건·검색어를 한 번에 뽑는다. (LLM 구조화 출력)

LLM 에게 정해진 형식(Understanding)으로만 답하게 해서, 결과를 그대로 파이썬 객체로 받는다.
    intent        "eligibility" = 내가 받을 수 있는지 묻는 질문 / "info" = 제도·절차 설명 질문
    household     이번 말에 새로 나온 가구 조건만 (말하지 않은 칸은 null)
    search_query  지침서에서 근거를 찾기 좋은 문장 — 일상어를 지침서 용어로 바꿔 쓴다
                  예) "일해서 번 돈은 얼마나 빼주나요?" → "생계급여 근로소득 공제 기준"
                  (5단계 평가에서 일상어 질문이 검색에 실패하던 문제의 대책)

숫자 계산은 시키지 않는다 — 금액을 원 단위로 옮겨 적는 것까지만. 판정은 판정 엔진이 한다.
"""

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.chat.state import HouseholdInfo
from app.config import LLM_CONTEXT_TOKENS, LLM_MODEL
from app.llm import make_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 국민기초생활보장 상담 챗봇의 "질문 이해" 단계입니다. 사용자의 마지막 말을 읽고 정해진 형식으로만 답합니다.

- intent: 사용자가 자기(또는 가족) 가구가 급여를 받을 수 있는지 알고 싶어 하면 "eligibility", 제도·절차·기준 자체를 묻는 질문이면 "info".
- household: 마지막 말에 새로 나온 가구 조건만 채우고, 나오지 않은 칸은 null 로 두세요. 추측해서 채우지 마세요.
  - region: 서울은 "서울", 경기도의 시·군은 "경기"입니다. 서울·경기는 광역시가 아닙니다.
  - 금액은 원 단위 정수로 옮기세요. 예) "월 150만원" → 1500000, "예금 700만원" → 7000000, "보증금 5천" → 50000000
  - 한 금액은 말한 칸 하나에만 넣으세요. 예금은 financial 에만 넣고, 말하지 않은 재산 칸은 null 로 두세요 (0 으로 채우지 말 것).
  - "재산 없어요"처럼 재산이 전혀 없다고 하면 재산 칸(housing, general, financial, car_full_rate, debt)을 모두 0 으로.
  - "소득 없어요"이면 earned_income 을 0 으로.
  - 사는 집이 전세·월세면 housing 에 보증금을 넣고 rented 를 true, 자기 집이면 rented 를 false 로.
  - deduction(근로소득공제 유형)은 일하는 사람에 대해 들은 대로: 34세 이하·대학생 → "60만원 + 30%",
    65세 이상·등록장애인·35세 이상 초중고생 → "20만원 + 30%", 임신 중·출산 6개월 미만·사회복무요원 → "30% 공제",
    장애인 직업재활 참여 → "20만원 + 50%", 물어봤는데 "해당 없어요"·"아니요"이면 → "일반".
    "모르겠어요"·"기억이 안 나요"처럼 답을 모르면 null (짐작해서 "일반"으로 채우지 말 것 — 코드가 따로 가정하고 표시한다). 들은 적 없으면 null.
- new_question: [방금 물어본 조건]이 있을 때만 판단합니다. 사용자가 그 질문에 답하지 않고 다른 것을 물으면 true
  (예: 지역을 물었는데 "그런데 해산급여가 뭐예요?"), 답했거나 "모르겠어요"·"없어요"처럼 답을 못 한 것이면 false.
- search_query: 지침서에서 근거 문단을 찾기 위한 한 문장. 일상어를 지침서 용어로 바꾸세요.
  예) "일해서 번 돈" → "근로소득", "빼주나요" → "공제", "장례비" → "장제급여", "아이 낳으면" → "해산급여"

예시 — 말에 나온 조건은 하나도 빠뜨리지 마세요:
말: "대구에서 셋이 살아요. 아내 월급 180만원, 재산은 없어요. 받을 수 있어요?"
→ {"intent": "eligibility", "household": {"size": 3, "region": "광역·세종·창원", "earned_income": 1800000, "housing": 0, "general": 0, "financial": 0, "car_full_rate": 0, "debt": 0}, "search_query": "생계급여 선정기준", "new_question": false}
[방금 물어본 조건] region / 말: "그런데 긴급복지는 뭐예요?"
→ {"intent": "info", "household": {}, "search_query": "긴급복지 지원", "new_question": true}
말: "광주 사는 4인 가족이고 소득은 없어요. 적금이 700만원 있는데 받을 수 있나요?"
→ {"intent": "eligibility", "household": {"size": 4, "region": "광역·세종·창원", "earned_income": 0, "financial": 7000000}, "search_query": "생계급여 선정기준", "new_question": false}
[방금 물어본 조건] region / 말: "수원이요"
→ {"intent": "eligibility", "household": {"region": "경기"}, "search_query": "생계급여 선정기준", "new_question": false}
"""

# 위기 판단은 전용 호출로 따로 묻는다: 긴 양식의 한 칸으로 물으면 로컬 모델이 위기 표현을 거의 놓쳤다 (같은 모델로 0/8 → 14/14)
SELF_HARM_PROMPT = """\
복지 상담 챗봇에 들어온 사용자의 말을 읽고, 사용자 본인이나 가족에게 자살·자해 위험이 있을 수 있는지 판단합니다.
직접 말하지 않아도 마지막 인사, 수단 준비, 삶을 끝내려는 암시, 극단적 절망이 보이면 true 입니다.
확실하지 않으면 true 를 고르세요. 놓치는 것이 더 위험합니다.
급여·제도·절차에 대한 평범한 질문과, 조건을 묻는 말에 대한 짧은 답은 false 입니다.

예시:
"그냥 끝낼래요" → true
"오늘이 마지막이에요" → true
"다들 고마웠어요 안녕" → true
"약을 모으고 있어요" → true
"이번 달로 급여가 끝나나요?" → false
"해산급여가 뭐예요?" → false
"이사 가면 주거급여가 달라지나요?" → false
"일자리를 잃었는데 어떤 지원이 있나요?" → false
"재산 없어요" → false
"모르겠어요" → false
"""

# 되묻는 중에 온 이 답들은 조건에 대한 답일 뿐이라 위기 판단을 건너뛴다 (모델이 "없어요"도 위험으로 봐서 되묻기가 끊겼다).
# 안전 규칙의 예외이므로 말 전체가 정확히 같을 때만, 되묻는 중일 때만 허용한다. 새 표현은 좁게 추가할 것
PLAIN_REPLIES = {
    "네", "예", "아니요", "아뇨", "없어요", "없습니다", "없음", "몰라요", "모르겠어요", "모르겠습니다", "잘모르겠어요", "잘모르겠네요",
    "기억이안나요", "해당없어요", "해당없습니다", "해당없음", "소득없어요", "소득없습니다", "재산없어요", "재산없습니다", "혼자살아요",
}


class SelfHarmCheck(BaseModel):
    """위기 판단 결과."""

    self_harm_risk: bool


class Extraction(BaseModel):
    """질문 이해 중 LLM 이 양식으로 채우는 부분."""

    intent: Literal["eligibility", "info"]
    household: HouseholdInfo
    search_query: str = Field(description="지침서 검색용 문장 (지침서 용어로)")
    new_question: bool = Field(
        False,
        description="[방금 물어본 조건]이 있는데 사용자가 그 답 대신 다른 질문을 했으면 true. 답을 모른다·없다고 한 것은 false",
    )


class Understanding(Extraction):
    """질문 이해 결과."""

    # 위기 감지의 두 번째 방어선 — 키워드 규칙(app/chat/crisis.py)이 못 잡는 문맥 의존 표현용. true 면 상담 전화 안내로 멈춘다
    self_harm_risk: bool = False


def has_self_harm_risk(message: str, client) -> bool:
    """사용자의 말 하나에 자살·자해 위험이 있는지 LLM 에게 묻는다. 답의 형식이 깨지면 위험으로 본다 (놓치는 쪽이 더 위험)."""
    response = client.chat(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": SELF_HARM_PROMPT}, {"role": "user", "content": message}],
        format=SelfHarmCheck.model_json_schema(),
        options={"temperature": 0, "num_ctx": LLM_CONTEXT_TOKENS},
    )
    try:
        return SelfHarmCheck.model_validate_json(response.message.content).self_harm_risk
    except ValidationError:
        logger.warning("위기 판단 결과의 형식이 맞지 않음: %r", response.message.content[:200])
        return True


def understand(messages: list[dict], known: HouseholdInfo, asked: list[str], client=None) -> Understanding:
    """대화 기록 → Understanding.

    messages: 지금까지의 대화 (마지막이 사용자의 말)
    known:    이미 모은 가구 조건 — 사용자가 "그대로예요" 같은 말을 해도 맥락을 알도록 같이 보여 줌
    asked:    방금 되물은 조건 이름 (예: ["region", "assets"]) — 짧은 답("서울이요")을 해석하는 단서
    client:   테스트에서 가짜를 넣는다. 없으면 새로 만든다.
    """
    client = client or make_client()
    last = messages[-1]["content"]
    plain_reply = asked and re.sub(r"[\s.,!~]", "", last) in PLAIN_REPLIES
    if not plain_reply and has_self_harm_risk(last, client):  # 위험하면 조건을 뽑을 필요 없이 멈춤 안내로 간다
        return Understanding(intent="info", household=HouseholdInfo(), search_query=messages[-1]["content"], self_harm_risk=True)
    context = (
        f"[이미 아는 가구 조건] {json.dumps(known.model_dump(exclude_none=True), ensure_ascii=False)}\n"
        f"[방금 물어본 조건] {', '.join(asked) if asked else '없음'}"
    )
    recent = messages[-10:]  # 최근 대화만 (오래된 대화는 조건이 이미 household 에 들어 있음)
    response = client.chat(
        model=LLM_MODEL,
        # 첫 user 메시지에 맥락을 붙여 보낸다 (system 은 고정)
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": context}, *recent],
        format=Extraction.model_json_schema(),  # Ollama 가 이 JSON 형식으로만 답하게 강제한다
        options={"temperature": 0, "num_ctx": LLM_CONTEXT_TOKENS},
    )
    try:
        return Understanding.model_validate_json(response.message.content)
    except ValidationError:
        # 형식이 깨지면 조건 없이 원래 질문으로 검색만 한다
        logger.warning("질문 이해 결과의 형식이 맞지 않음: %r", response.message.content[:200])
        return Understanding(intent="info", household=HouseholdInfo(), search_query=messages[-1]["content"])
