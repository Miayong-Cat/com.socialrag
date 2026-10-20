"""소득평가액 계산 — "이 가구의 소득을 판정에서 얼마로 보는가?"

소득평가액 = 실제소득 − 가구특성별 지출비용 − 근로소득공제          (p.77, p.125)
    실제소득        = 근로·사업소득 합계 + 그 밖의 소득
    근로소득공제    = 소득자마다 공제 유형에 따라 계산한 금액의 합 (p.131~132)
    결과가 음수면 0원으로 처리 (p.125)

급여마다 결과가 다를 수 있다:
    일반 수급자의 근로소득 30% 공제는 생계·주거·교육급여에만 있고 의료급여에는 없다.
    → 같은 가구라도 의료급여의 소득평가액이 더 크게 나올 수 있다.

예) 일반 근로자 1명, 월 100만원
    생계급여: 100만 − 30만(30%) = 70만원
    의료급여: 100만 − 0          = 100만원

원 미만 처리: 지침서 본문에서 규정을 찾지 못해 "원 미만 버림"으로 계산한다 (확인 필요).
"""

from app.eligibility.household import Earner, Household, WorkDeduction
from app.eligibility.standards import GENERAL_DEDUCTION_PROGRAMS, WORK_DEDUCTION_RULES


def deduction_by_rule(income: int, base: int, percent: float) -> int:
    """공제 규칙 하나로 공제액을 계산한다.

    income:  월 근로·사업소득
    base:    먼저 통째로 빼 주는 금액 (예: 20만원)
    percent: base 를 빼고 남은 소득에 대한 공제율 % (예: 30)

    예) income=1,000,000, base=200,000, percent=30
        → 200,000 + (800,000 × 30%) = 440,000
    소득이 base 보다 적으면 소득 전체가 공제된다 (공제액이 소득보다 클 수 없음).
    """
    if income <= base:
        return income
    return base + int((income - base) * percent / 100)  # int() → 원 미만 버림


def work_deduction(earner: Earner, program: str) -> int:
    """소득자 한 명의 근로소득공제액. 급여 종류(program)에 따라 달라질 수 있다.

    일반 수급자(GENERAL)는 생계·주거·교육급여에서만 30% 공제, 의료급여에서는 0원.
    """
    if earner.deduction is WorkDeduction.GENERAL and program not in GENERAL_DEDUCTION_PROGRAMS:
        return 0  # 의료급여의 일반 수급자: 공제 없음
    base, percent = WORK_DEDUCTION_RULES[earner.deduction]
    return deduction_by_rule(earner.monthly_income, base, percent)


def income_evaluation(household: Household, program: str) -> int:
    """가구의 소득평가액(원/월). program 은 급여 이름 (예: "생계급여")."""
    earned = sum(e.monthly_income for e in household.earners)                  # 근로·사업소득 합계
    deductions = sum(work_deduction(e, program) for e in household.earners)    # 근로소득공제 합계
    actual_income = earned + household.other_income                            # 실제소득
    result = actual_income - household.household_expenses - deductions
    return max(result, 0)  # 음수면 0원 (p.125)
