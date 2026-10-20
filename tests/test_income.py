"""소득평가액 테스트 (대상: app/eligibility/income.py).

공제 규칙(p.131~132)을 유형별로 하나씩 확인한다.
특히 "의료급여에는 일반 30% 공제가 없다"는 점이 핵심.

실행:
    pytest tests/test_income.py
"""

import pytest

from app.eligibility.household import Earner, Household, Region, WorkDeduction
from app.eligibility.income import income_evaluation


def one_earner(income: int, deduction: WorkDeduction = WorkDeduction.GENERAL, **extra) -> Household:
    """소득자 1명인 서울 1인 가구를 만드는 도우미 함수. extra 로 다른 칸(other_income 등)을 더 줄 수 있다."""
    return Household(size=1, region=Region.SEOUL, earners=[Earner(income, deduction)], **extra)


def test_general_earner_30_percent_except_medical():
    """일반 수급자 월 100만원: 생계·주거·교육은 30% 공제 → 70만, 의료는 공제 없음 → 100만."""
    household = one_earner(1_000_000)
    assert income_evaluation(household, "생계급여") == 700_000
    assert income_evaluation(household, "주거급여") == 700_000
    assert income_evaluation(household, "교육급여") == 700_000
    assert income_evaluation(household, "의료급여") == 1_000_000


# parametrize → (공제 유형, 기대 소득평가액) 조합마다 아래 테스트를 한 번씩 실행
@pytest.mark.parametrize(
    "deduction, expected",
    [
        (WorkDeduction.FLAT_30, 700_000),      # 100만 − 30만
        (WorkDeduction.BASE_200K, 560_000),    # 100만 − (20만 + 80만×30% = 44만)
        (WorkDeduction.YOUTH, 280_000),        # 100만 − (60만 + 40만×30% = 72만)
        (WorkDeduction.VOCATIONAL, 400_000),   # 100만 − (20만 + 80만×50% = 60만)
    ],
)
def test_special_deductions_apply_to_medical_too(deduction, expected):
    """노인·장애인·청년 등 특정 유형 공제는 의료급여에도 똑같이 적용된다 (p.131 표 "생계･의료･주거･교육급여")."""
    household = one_earner(1_000_000, deduction)
    assert income_evaluation(household, "생계급여") == expected
    assert income_evaluation(household, "의료급여") == expected


def test_income_below_base_is_fully_deducted():
    """청년(60만원 공제) 소득이 50만원이면 전부 공제 → 0원 (공제액이 소득보다 클 수 없음)."""
    assert income_evaluation(one_earner(500_000, WorkDeduction.YOUTH), "생계급여") == 0


def test_other_income_has_no_deduction():
    """재산소득·이전소득 등 그 밖의 소득에는 근로소득공제가 없다 (p.131).
    근로 100만(30% 공제 → 70만) + 그 밖의 소득 20만 = 90만
    """
    assert income_evaluation(one_earner(1_000_000, other_income=200_000), "생계급여") == 900_000


def test_household_expenses_and_negative_becomes_zero():
    """가구특성별 지출비용을 빼고, 결과가 음수면 0원 (p.125)."""
    household = one_earner(1_000_000, household_expenses=100_000)
    assert income_evaluation(household, "생계급여") == 600_000  # 70만 − 10만

    big_expenses = one_earner(1_000_000, household_expenses=900_000)
    assert income_evaluation(big_expenses, "생계급여") == 0  # 70만 − 90만 = −20만 → 0


def test_multiple_earners_each_get_own_deduction():
    """공제는 사람마다 따로 계산해서 더한다.
    일반 100만(30만 공제) + 65세 이상 50만(20만 + 30만×30% = 29만 공제) → 150만 − 59만 = 91만
    """
    household = Household(
        size=2,
        region=Region.SEOUL,
        earners=[Earner(1_000_000), Earner(500_000, WorkDeduction.BASE_200K)],
    )
    assert income_evaluation(household, "생계급여") == 910_000
