"""선정기준액 계산 — "이 가구는 소득이 얼마 이하여야 하는가?"를 원 단위로 계산한다.

선정기준액 = 급여를 받을 수 있는 소득의 상한선 (원/월).
LLM 없이 지침서에 적힌 산식을 그대로 옮긴 순수 함수만 둔다 (DB·파일 접근 없음).

근거: 2026 국민기초생활보장 사업안내
- p.14  급여별 선정기준액 = 기준 중위소득 × 비율 (원 단위 반올림)
- p.78  8인 이상 가구: 1인 늘 때마다 (7인 기준 − 6인 기준)을 7인 기준에 더함

예) 2026년 1인 가구 생계급여(32%):
    2,564,238원 × 32% = 820,556.16 → 반올림 → 820,556원
"""

TABLE_MAX_SIZE = 7  # 지침서 표에 나오는 최대 가구원 수 (1인 ~ 7인)


def percent_of(amount: int, percent: float) -> int:
    """amount 의 percent% 를 원 단위로 반올림해서 돌려준다.

    + 0.5 후 int() 로 자르는 이유:
        파이썬 기본 round() 는 0.5를 짝수 쪽으로 보내는 "은행가 반올림"이라
        (round(2.5) == 2) 지침서 표와 1원씩 어긋날 수 있다.
        +0.5 후 소수점을 버리면 일반적인 사사오입이 된다. (금액은 항상 양수)
    """
    return int(amount * percent / 100 + 0.5)


def extend_to_size(amounts: dict[int, int], household_size: int) -> int:
    """1~7인 표에서 가구원 수에 맞는 값을 꺼낸다. 8인 이상은 p.78 규칙으로 늘린다.

    amounts:        {가구원 수: 금액} — 1~7인이 모두 들어 있어야 함
    household_size: 알고 싶은 가구원 수 (1 이상)
    반환:           그 가구원 수의 금액

    8인 이상 예) step = 7인 금액 − 6인 금액
        8인 = 7인 + step × 1
        9인 = 7인 + step × 2
    """
    if household_size < 1:
        raise ValueError("가구원 수는 1명 이상이어야 합니다.")
    if household_size <= TABLE_MAX_SIZE:
        return amounts[household_size]  # 표 안에 있으면 그대로
    step = amounts[7] - amounts[6]      # 1인이 늘 때마다 더하는 금액
    return amounts[7] + step * (household_size - TABLE_MAX_SIZE)


def selection_threshold(median_incomes: dict[int, int], percent: float, household_size: int) -> int:
    """급여 하나의 선정기준액(원/월)을 계산한다.

    median_incomes: {가구원 수: 기준 중위소득} — 1~7인 (DB의 median_incomes 테이블 값)
    percent:        기준 중위소득 대비 % — 예) 생계급여 32
    household_size: 가구원 수

    계산 순서:
        1. 먼저 1~7인 선정기준 "표"를 만들고 (중위소득 × 비율, 칸마다 반올림)
        2. 8인 이상은 그 "표"를 p.78 규칙으로 늘린다.
    p.78 규칙이 "급여별 선정기준표의 7인 − 6인"을 더하라고 하므로 이 순서를 따른다.
    (결과는 지침서 p.14 주석의 8인 생계급여 3,351,791원과 일치 — tests/test_eligibility.py)
    """
    # {1: 820556, 2: 1343773, …, 7: 3044848} 처럼 1~7인 선정기준표를 만든다.
    table = {size: percent_of(median_incomes[size], percent) for size in range(1, TABLE_MAX_SIZE + 1)}
    return extend_to_size(table, household_size)
