"""챗봇 상태 — 대화 하나(thread)가 끝날 때까지 들고 다니는 데이터와, 가구 조건 수집 규칙.

ChatState 는 LangGraph 노드들이 읽고 고치는 "공용 보관함"이다. (자바로 치면 세션에 담아 두는 DTO)
체크포인터가 대화(thread_id)마다 저장해 두므로, 다음 질문에서도 이미 모은 가구 조건이 남아 있다.

가구 조건(HouseholdInfo)은 사용자가 말한 것만 채우고, 모르는 칸은 None 으로 둔다.
    None = 아직 모름 (물어봐야 함)
    0    = 없다고 들음 ("재산 없어요" → 재산 칸 0)
판정에 꼭 필요한 조건(REQUIRED)이 다 모이면 판정 엔진(app/eligibility/)을 부른다.
"""

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

from app.eligibility.asset import housing_value
from app.eligibility.household import Earner, Household, Region, WorkDeduction

RegionName = Literal["서울", "경기", "광역·세종·창원", "그 외 지역"]
DeductionName = Literal["일반", "30% 공제", "20만원 + 30%", "60만원 + 30%", "20만원 + 50%"]


class HouseholdInfo(BaseModel):
    """대화에서 모은 가구 조건. 금액은 모두 원 단위. (Claude 구조화 출력의 형식으로도 쓴다)"""

    size: int | None = Field(None, description="가구원 수 (본인 포함)")
    region: RegionName | None = Field(
        None, description="거주 지역. 광역시(부산·대구·인천·광주·대전·울산)와 세종·창원은 '광역·세종·창원', 그 밖의 시·군은 '그 외 지역'"
    )
    earned_income: int | None = Field(None, description="가구 전체 월 근로·사업소득 합계(원). 없다고 하면 0")
    deduction: DeductionName | None = Field(
        None,
        description=(
            "소득자의 근로소득공제 유형. 일반=보통, '30% 공제'=임신·출산 6개월 미만·사회복무요원, "
            "'20만원 + 30%'=65세 이상·등록장애인·35세 이상 학생, '60만원 + 30%'=34세 이하·대학생, "
            "'20만원 + 50%'=장애인 직업재활 참여. 해당 사항이 없다고 하면 '일반', 말하지 않았으면 null"
        ),
    )
    other_income: int | None = Field(None, description="그 밖의 월 소득(원): 연금·임대료·이자·정기 지원금 등")
    housing: int | None = Field(None, description="사는 집 가액(원): 자가면 집값, 전·월세면 보증금")
    rented: bool | None = Field(None, description="사는 집이 전세·월세라 housing 이 보증금이면 true, 자가면 false")
    general: int | None = Field(None, description="사는 집이 아닌 토지·건물 등 일반재산(원)")
    financial: int | None = Field(None, description="예금·적금·주식·보험 등 금융재산(원)")
    car_full_rate: int | None = Field(None, description="자동차 가액(원). 생업용·장애인용이 아닌 일반 승용차")
    debt: int | None = Field(None, description="대출 등 부채(원)")


ASSET_FIELDS = ("housing", "general", "financial", "car_full_rate", "debt")

# 판정에 꼭 필요한 조건 → 사용자에게 물을 문장. (재산은 칸이 많아 한 번에 묻는다)
REQUIRED: dict[str, str] = {
    "size": "가구원은 본인을 포함해 모두 몇 명인가요?",
    "region": "어디에 사시나요? (서울 / 경기 / 광역시·세종·창원 / 그 밖의 시·군)",
    "income": "가구 전체가 일해서 버는 돈(근로·사업소득)은 한 달에 얼마인가요? 없으면 '없음'이라고 해 주세요.",
    "deduction": (
        "일하시는 분이 다음 중 해당되는 게 있나요? 공제가 달라져요. "
        "(34세 이하·대학생 / 65세 이상·등록장애인·35세 이상 학생 / 임신 중·출산 6개월 미만·사회복무요원 / "
        "장애인 직업재활 참여 / 해당 없음)"
    ),
    "assets": "재산을 알려 주세요 — 사는 집(자가면 집값, 전·월세면 보증금), 예금·적금, 자동차, 대출. 없으면 '없음'.",
}


# 같은 조건을 이만큼 물어도 답을 못 들으면 더 묻지 않는다 — "모르겠어요"에 같은 질문을 끝없이 반복하지 않게
MAX_ASKS = 2
# 답을 못 들었을 때 가정하고 판정해도 되는 조건 → 가정값 (공제가 가장 작은 쪽 = 신청자에게 불리한 쪽으로 가정)
#   나머지 조건(가구원 수·지역·소득·재산)은 가정하면 판정이 의미 없으므로 판정을 멈추고 안내한다
ASSUMABLE = {"deduction": "일반"}
FIELD_LABELS = {"size": "가구원 수", "region": "사는 지역", "income": "근로·사업소득", "deduction": "공제 유형", "assets": "재산"}


def missing_fields(info: HouseholdInfo) -> list[str]:
    """아직 모르는 필수 조건 이름 목록 (REQUIRED 순서)."""
    missing = []
    if info.size is None:
        missing.append("size")
    if info.region is None:
        missing.append("region")
    if info.earned_income is None:
        missing.append("income")
    elif info.earned_income > 0 and info.deduction is None:
        # 공제 유형에 따라 공제액이 크게 다르다 (월 100만원: 일반 30만 vs 34세 이하 72만) — 기본값으로 짐작하지 않고 묻는다
        missing.append("deduction")
    if all(getattr(info, f) is None for f in ASSET_FIELDS):  # 재산 칸이 하나라도 채워지면 답한 것으로 봄
        missing.append("assets")
    return missing


def question_for(fields: list[str]) -> str:
    """부족한 조건을 묻는 문장. LLM 없이 정해진 문장을 쓴다 (항상 같은 질문 → 예측 가능, 비용 없음)."""
    if len(fields) == 1:
        return REQUIRED[fields[0]]
    lines = [f"{i}. {REQUIRED[f]}" for i, f in enumerate(fields, start=1)]
    return "판정하려면 몇 가지가 더 필요해요.\n" + "\n".join(lines)


def merge(old: HouseholdInfo, new: HouseholdInfo) -> HouseholdInfo:
    """새로 들은 조건(None 이 아닌 칸)으로 덮어쓴다. 사용자가 정정하면 새 값이 이긴다."""
    return old.model_copy(update=new.model_dump(exclude_none=True))


def to_household(info: HouseholdInfo) -> Household:
    """수집한 조건 → 판정 엔진 입력. 모르는 금액은 0으로 본다 (필수 조건은 이미 채워진 상태에서 부름).

    근로소득은 가구 합계 하나로 받으므로 소득자 1명으로 계산한다 (소득자별 공제 유형이 다르면 오차 가능).
    공제 유형은 근로소득이 있으면 missing_fields 가 물어보므로 여기서는 이미 채워져 있다 ("일반"은 안전장치).
    """
    earners = []
    if info.earned_income:
        earners = [Earner(info.earned_income, WorkDeduction(info.deduction or ASSUMABLE["deduction"]))]
    return Household(
        size=info.size,
        region=Region(info.region),
        earners=earners,
        other_income=info.other_income or 0,
        housing=housing_value(info.housing or 0, bool(info.rented)),
        general=info.general or 0,
        financial=info.financial or 0,
        car_full_rate=info.car_full_rate or 0,
        debt=info.debt or 0,
    )


class ChatState(TypedDict, total=False):
    """그래프 노드들이 같이 쓰는 상태. total=False → 모든 칸이 처음엔 비어 있어도 됨."""

    # 대화 기록 [{"role": "user"|"assistant", "content": "…"}]
    #   Annotated[…, operator.add] → 노드가 돌려준 목록을 덮어쓰지 않고 뒤에 이어 붙인다
    messages: Annotated[list[dict], operator.add]
    intent: str                 # "eligibility"(수급 가능 여부) / "info"(제도 설명)
    question: str               # 이번 턴의 원래 질문 (되묻기 답변이 아니라 처음 물은 것)
    search_query: str           # 지침서 검색용으로 바꿔 쓴 질문
    household: dict             # 모은 가구 조건 (HouseholdInfo.model_dump())
    pending_fields: list[str]   # 아직 모르는 필수 조건 — 비어 있지 않으면 되묻는 중
    ask_counts: dict            # {조건: 이번 질문에서 물어본 횟수} — MAX_ASKS 를 넘기면 더 묻지 않음
    assumed: list[str]          # 답을 못 들어 가정하고 판정한 조건 (ASSUMABLE) — 답변에 "가정함" 표시
    eligibility: list[dict]     # 판정 결과 (app/schemas.py 의 ProgramJudgement)
    passages: list[dict]        # 검색한 지침서 청크 {page, section, heading, text}
    crisis: str                 # 이번 메시지의 위기 신호 종류 ("" = 없음) — app/chat/crisis.py
    notice: str                 # 답 앞에 붙일 위기 안내 ("" = 없음)
    answer: str                 # 이번 턴의 최종 답변
    sources: list[dict]         # 답변 근거 {page, section, quote}
