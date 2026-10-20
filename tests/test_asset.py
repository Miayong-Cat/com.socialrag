"""재산의 소득환산액 테스트 (대상: app/eligibility/asset.py).

앞의 세 테스트는 지침서에 실린 계산 예시를 그대로 옮겼다 (p.160, p.191~192).
나머지는 계산 순서 규칙(생활준비금, 부채 순서, 100% 자동차)을 하나씩 확인한다.

실행:
    pytest tests/test_asset.py
"""

from app.eligibility.asset import asset_conversion
from app.eligibility.household import Household, Region

MAN = 10_000  # 만원 → 원 (지침서 예시가 만원 단위라 읽기 쉽게)


def sejong(**assets) -> Household:
    """세종시 1인 가구를 만든다. 지침서 예시가 모두 세종시라서 만든 도우미 함수.

    **assets → sejong(housing=…, general=…) 처럼 이름을 붙여 넘긴 값을 그대로 Household 에 전달.
    """
    return Household(size=1, region=Region.METRO, **assets)


def test_guide_example_housing_over_cap():
    """p.160: 세종, 주거용재산 1억5,600만원
    한도(1억4,600만) 초과 1,000만 → 일반재산 4.17% = 417,000
    1억4,600만 − 기본재산액 7,700만 = 6,900만 → 1.04% = 717,600
    """
    assert asset_conversion(sejong(housing=15_600 * MAN)) == 417_000 + 717_600


def test_guide_example_1_housing_and_general():
    """p.191 예시1: 세종, 주거용재산 1억6,600만원 + 일반재산 3천만원
    일반재산 (초과분 2천만 + 3천만) × 4.17% = 2,085,000
    주거용재산 (1억4,600만 − 7,700만) × 1.04% = 717,600
    """
    household = sejong(housing=16_600 * MAN, general=3_000 * MAN)
    assert asset_conversion(household) == 2_085_000 + 717_600


def test_guide_example_2_small_housing():
    """p.192 예시2: 세종, 주거용재산 7,800만원 (생업용 자동차는 재산에서 제외 → 입력하지 않음)
    7,800만 − 7,700만 = 100만 → 1.04% = 10,400
    """
    assert asset_conversion(sejong(housing=7_800 * MAN)) == 10_400


def test_basic_deduction_moves_to_next_property():
    """기본재산액은 주거용 → 일반 → 금융 순서로 뺀다 (p.191).
    주거용 3천만 + 일반 6천만, 세종 기본재산액 7,700만
    → 주거용 0, 일반 1,300만만 남음 → 1,300만 × 4.17% = 542,100
    """
    assert asset_conversion(sejong(housing=3_000 * MAN, general=6_000 * MAN)) == 542_100


def test_living_reserve_for_financial():
    """금융재산에서 생활준비금 500만원을 먼저 뺀다 (p.174).
    서울(기본재산액 9,900만), 금융재산 1억
        → 1억 − 생활준비금 500만 = 9,500만 → 기본재산액 9,900만을 빼면 음수 → 0원
    (생활준비금을 빼지 않았다면 1억 − 9,900만 = 100만 × 6.26% = 62,600원이 나왔을 것)
    """
    household = Household(size=1, region=Region.SEOUL, financial=10_000 * MAN)
    assert asset_conversion(household) == 0


def test_debt_order_housing_first():
    """부채도 주거용 → 일반 → 금융 순서로 뺀다 (p.189).
    그 외 지역(기본재산액 5,300만), 주거용 5,300만 + 일반 2천만, 부채 1천만
    → 기본재산액으로 주거용 0 → 부채 1천만은 일반재산에서 → 일반 1천만 × 4.17% = 417,000
    """
    household = Household(
        size=1, region=Region.OTHER, housing=5_300 * MAN, general=2_000 * MAN, debt=1_000 * MAN
    )
    assert asset_conversion(household) == 417_000


def test_full_rate_car_gets_no_deduction():
    """100% 자동차는 기본재산액이 남아도 공제하지 않고 가액 전체를 월 소득으로 본다 (p.191).
    서울, 다른 재산 없음, 100% 자동차 300만원 → 3,000,000
    """
    household = Household(size=1, region=Region.SEOUL, car_full_rate=300 * MAN, debt=100 * MAN)
    assert asset_conversion(household) == 3_000_000


def test_no_property_is_zero():
    """재산이 없으면 0원."""
    assert asset_conversion(Household(size=1, region=Region.SEOUL)) == 0
