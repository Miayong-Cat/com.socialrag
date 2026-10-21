"""재산의 소득환산액 계산 — "이 가구의 재산을 월 소득으로 치면 얼마인가?"

재산의 소득환산액 = (재산 − 기본재산액 − 부채) × 재산 종류별 소득환산율     (p.77, p.191)

계산 순서 (순서가 바뀌면 결과가 달라지므로 지침서 순서를 그대로 따른다):
    1. 주거용재산 중 지역별 한도액을 넘는 부분 → 일반재산으로 옮김         (p.160)
    2. 금융재산에서 생활준비금 500만원 빼기                                (p.174)
    3. 기본재산액을 주거용 → 일반 → 금융재산 순서로 빼기                    (p.191)
    4. 부채를 주거용 → 일반 → 금융재산 순서로 빼기                          (p.189)
    5. 종류별 환산율을 곱해 더하기: 주거용 1.04%, 일반 4.17%, 금융 6.26%     (p.192)
       소득환산율 100% 자동차는 기본재산액·부채를 빼지 않고 가액 전체에 100%  (p.189, p.191)

예) 세종시, 주거용재산 1억6,600만원 + 일반재산 3천만원  (p.191 예시1)
    1. 한도 1억4,600만원 초과분 2천만원 → 일반재산 (일반재산 5천만원)
    3. 기본재산액 7,700만원을 주거용재산에서 뺌 → 주거용재산 6,900만원
    5. 6,900만 × 1.04% + 5,000만 × 4.17% = 717,600 + 2,085,000 = 2,802,600원

아직 계산하지 않는 것 (지침서 세부 규칙 — 필요해지면 추가):
    - 장기금융저축공제 (p.174), 재산범위 특례 (p.193~195), 자동차 유형별 판정 (p.192~)

원 미만 처리: 지침서 본문에서 규정을 찾지 못해 "원 미만 버림"으로 계산한다 (확인 필요).
"""

from app.eligibility.household import Household
from app.eligibility.money import apply_rate, rate_floor  # 금액 × % (Decimal — app/eligibility/money.py)
from app.eligibility.standards import (
    BASIC_PROPERTY_DEDUCTION,
    CONVERSION_RATE,
    DEPOSIT_RATE,
    HOUSING_CAP,
    LIVING_RESERVE,
)

# 기본재산액·부채를 빼는 순서 (p.189, p.191)
DEDUCTION_ORDER = ("housing", "general", "financial")


def subtract_in_order(amounts: dict[str, int], deduction: int) -> dict[str, int]:
    """deduction 금액을 DEDUCTION_ORDER 순서대로 각 재산에서 뺀다. 남은 재산 금액을 돌려준다.

    앞 재산이 0이 되면 남은 공제액을 다음 재산에서 뺀다.
    모든 재산을 0으로 만들고도 공제액이 남으면 버린다 (100% 자동차에서는 빼지 않음).

    예) amounts={"housing": 3천만, "general": 1천만, "financial": 0}, deduction=3,500만
        → housing 0 (3천만 뺌), general 500만 (나머지 500만 뺌), financial 0
    """
    result = dict(amounts)  # 원본을 바꾸지 않도록 복사
    for kind in DEDUCTION_ORDER:
        used = min(result[kind], deduction)  # 이 재산에서 뺄 수 있는 만큼만
        result[kind] -= used
        deduction -= used
    return result


def asset_conversion(household: Household) -> int:
    """가구의 재산의 소득환산액(원/월). 급여 종류와 상관없이 같다 (기초생활보장 4종 모두 같은 기준)."""
    # 1. 주거용재산 한도 초과분은 일반재산으로
    cap = HOUSING_CAP[household.region]
    housing = min(household.housing, cap)
    over_cap = household.housing - housing  # 한도를 넘는 금액 (넘지 않으면 0)

    # 2. 금융재산에서 생활준비금 빼기 (음수가 되지 않게 max)
    financial = max(household.financial - LIVING_RESERVE, 0)

    amounts = {
        "housing": housing,
        "general": household.general + over_cap,
        "financial": financial,
    }

    # 3. 기본재산액 빼기 → 4. 부채 빼기 (둘 다 같은 순서)
    amounts = subtract_in_order(amounts, BASIC_PROPERTY_DEDUCTION[household.region])
    amounts = subtract_in_order(amounts, household.debt)

    # 5. 종류별 환산율을 곱해 더하기
    converted = sum(apply_rate(amounts[kind], CONVERSION_RATE[kind]) for kind in DEDUCTION_ORDER)
    converted += apply_rate(household.car_full_rate, CONVERSION_RATE["car_full_rate"])
    return int(converted)  # 원 미만 버림


def housing_value(amount: int, rented: bool) -> int:
    """사는 집의 재산 가액(Household.housing 에 넣을 값). 자가면 집값 그대로, 전·월세면 보증금의 95% (p.164).

    챗봇(app/chat/state.py)과 판정 API(app/schemas.py)가 같이 쓴다 — 화면마다 따로 계산하면 결과가 어긋난다.
    """
    return rate_floor(amount, DEPOSIT_RATE) if rented else amount  # 원 미만 버림
