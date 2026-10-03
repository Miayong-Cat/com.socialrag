"""선정기준 판정 규칙. LLM 없이 지침서 산식 그대로 계산하는 순수 함수만 둔다.

근거: 2026 국민기초생활보장 사업안내
- p.13  선정기준은 "~이하": 소득인정액 ≦ 선정기준액이면 충족
- p.14  급여별 선정기준액 = 기준 중위소득 × 비율 (원 단위 반올림)
- p.78  8인 이상 가구: 1인 늘 때마다 (7인 기준 − 6인 기준)을 7인 기준에 더함
"""

from dataclasses import dataclass

TABLE_MAX_SIZE = 7  # 지침서 표에 나오는 최대 가구원 수


def percent_of(amount: int, percent: float) -> int:
    """amount × percent% 를 원 단위로 반올림."""
    return int(amount * percent / 100 + 0.5)


def extend_to_size(amounts: dict[int, int], household_size: int) -> int:
    """1~7인 표에서 가구원 수에 맞는 값을 꺼낸다. 8인 이상은 p.78 규칙으로 늘린다."""
    if household_size < 1:
        raise ValueError("가구원 수는 1명 이상이어야 합니다.")
    if household_size <= TABLE_MAX_SIZE:
        return amounts[household_size]
    step = amounts[7] - amounts[6]
    return amounts[7] + step * (household_size - TABLE_MAX_SIZE)


def selection_threshold(median_incomes: dict[int, int], percent: float, household_size: int) -> int:
    """급여 하나의 선정기준액(원/월). 표(1~7인)를 먼저 만들고, 8인 이상은 그 표를 늘린다."""
    table = {size: percent_of(median_incomes[size], percent) for size in range(1, TABLE_MAX_SIZE + 1)}
    return extend_to_size(table, household_size)


@dataclass
class Judgement:
    program: str
    threshold: int     # 선정기준액(원/월)
    eligible: bool     # 소득인정액 ≦ 선정기준액
    margin: int        # 선정기준액 − 소득인정액 (음수면 그만큼 초과)


def judge(
    household_size: int,
    recognized_income: int,
    median_incomes: dict[int, int],
    programs: dict[str, float],
) -> list[Judgement]:
    """가구원 수와 소득인정액으로 제도별 충족 여부를 판정한다.

    median_incomes: {가구원 수: 기준 중위소득}  (1~7인)
    programs:       {제도 이름: 기준 중위소득 대비 %}  예) {"생계급여": 32}
    """
    if recognized_income < 0:
        raise ValueError("소득인정액은 0원 이상이어야 합니다. (지침서: 음수는 0원 처리)")

    results = []
    for name, percent in programs.items():
        threshold = selection_threshold(median_incomes, percent, household_size)
        results.append(
            Judgement(
                program=name,
                threshold=threshold,
                eligible=recognized_income <= threshold,
                margin=threshold - recognized_income,
            )
        )
    return results
