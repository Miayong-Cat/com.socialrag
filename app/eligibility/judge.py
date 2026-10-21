"""충족 여부 판정 — 가구의 소득인정액이 제도별 선정기준액 이하인지 판정한다.

선정기준액 계산은 threshold.py, 소득인정액 계산은 income.py + asset.py 가 맡고,
이 파일은 "계산 결과를 비교해서 판정 결과를 만드는 일"만 한다.

근거: 2026 국민기초생활보장 사업안내
- p.13  선정기준은 "~이하": 소득인정액 ≦ 선정기준액이면 충족 (같아도 충족)
- p.77  소득인정액 = 소득평가액 + 재산의 소득환산액

함수 두 개:
    judge(...)            소득인정액을 이미 알 때 — 숫자 하나로 모든 제도를 판정
    judge_household(...)  가구 정보(Household)를 줄 때 — 제도마다 소득인정액을 계산해서 판정
                          (근로소득공제가 급여마다 달라 소득인정액도 제도마다 다를 수 있음)

사용 예:
    judge_household(
        Household(size=1, region=Region.SEOUL, earners=[Earner(1_100_000)]),
        median_incomes={1: 2_564_238, …, 7: 9_515_150},
        programs={"생계급여": 32, "의료급여": 40},
    )
    → 생계급여: 소득인정액 770,000 (30% 공제) ≦ 820,556  → 충족
      의료급여: 소득인정액 1,100,000 (공제 없음) > 1,025,695 → 미충족
"""

from dataclasses import dataclass  # 값만 담는 간단한 클래스를 만드는 도구 (자바의 record와 비슷)

from app.eligibility.asset import asset_conversion
from app.eligibility.household import Household
from app.eligibility.income import income_evaluation, total_work_deduction
from app.eligibility.threshold import selection_threshold


@dataclass
class Judgement:
    """제도 하나에 대한 판정 결과."""

    program: str             # 제도 이름. 예: "생계급여"
    recognized_income: int   # 소득인정액(원/월) — 판정에 쓴 가구 소득
    threshold: int           # 선정기준액(원/월)
    eligible: bool           # 충족 여부 = 소득인정액 ≦ 선정기준액
    margin: int              # 선정기준액 − 소득인정액. 양수 = 여유 금액, 음수 = 초과 금액
    # 계산 내역 — judge_household 가 채운다 (judge 는 소득인정액만 받으므로 0). 화면·답변의 "계산 근거"에 쓴다
    earned_income: int = 0       # 근로·사업소득 합계
    work_deduction: int = 0      # 근로소득공제액 (급여마다 다를 수 있음)
    income_evaluation: int = 0   # 소득평가액
    asset_conversion: int = 0    # 재산의 소득환산액


def judge(
    household_size: int,
    recognized_income: int,
    median_incomes: dict[int, int],
    programs: dict[str, float],
) -> list[Judgement]:
    """가구원 수와 소득인정액으로 제도별 충족 여부를 판정한다.

    household_size:    가구원 수 (1 이상)
    recognized_income: 소득인정액(원/월) = 소득평가액 + 재산의 소득환산액 (0 이상)
    median_incomes:    {가구원 수: 기준 중위소득} — 1~7인
    programs:          {제도 이름: 기준 중위소득 대비 %} — 예) {"생계급여": 32}
    반환:              programs 에 넣은 순서대로 Judgement 목록
    """
    # 지침서는 계산 결과가 음수면 0원으로 처리하라고 한다.
    # 음수가 들어왔다는 건 앞 단계 계산이 잘못됐다는 뜻이라 조용히 넘기지 않고 에러를 낸다.
    if recognized_income < 0:
        raise ValueError("소득인정액은 0원 이상이어야 합니다. (지침서: 음수는 0원 처리)")

    results = []
    for name, percent in programs.items():
        threshold = selection_threshold(median_incomes, percent, household_size)
        results.append(
            Judgement(
                program=name,
                recognized_income=recognized_income,
                threshold=threshold,
                eligible=recognized_income <= threshold,  # "이하"이므로 <= (같아도 충족)
                margin=threshold - recognized_income,
            )
        )
    return results


def judge_household(
    household: Household,
    median_incomes: dict[int, int],
    programs: dict[str, float],
) -> list[Judgement]:
    """가구 정보로 제도마다 소득인정액을 계산한 뒤 충족 여부를 판정한다.

    household:      판정할 가구 (app/eligibility/household.py)
    median_incomes: {가구원 수: 기준 중위소득} — 1~7인
    programs:       {제도 이름: 기준 중위소득 대비 %}
    반환:           programs 에 넣은 순서대로 Judgement 목록
    """
    results = []
    earned = sum(e.monthly_income for e in household.earners)
    asset = asset_conversion(household)  # 재산 환산액은 제도와 상관없이 같다
    for name, percent in programs.items():
        evaluation = income_evaluation(household, name)  # 이 제도 기준의 소득평가액 (공제가 제도마다 다를 수 있음)
        # 제도 하나만 넣어 judge() 를 부르고, 결과 목록의 첫 번째([0])를 꺼내 계산 내역을 붙인다.
        result = judge(household.size, evaluation + asset, median_incomes, {name: percent})[0]
        result.earned_income, result.work_deduction = earned, total_work_deduction(household, name)
        result.income_evaluation, result.asset_conversion = evaluation, asset
        results.append(result)
    return results
