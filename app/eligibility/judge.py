"""충족 여부 판정 — 가구의 소득인정액이 제도별 선정기준액 이하인지 판정한다.

선정기준액 계산은 threshold.py 가 맡고, 이 파일은 "비교해서 결과를 만드는 일"만 한다.

근거: 2026 국민기초생활보장 사업안내
- p.13  선정기준은 "~이하": 소득인정액 ≦ 선정기준액이면 충족 (같아도 충족)

사용 예:
    judge(
        household_size=1,
        recognized_income=800_000,
        median_incomes={1: 2_564_238, …, 7: 9_515_150},
        programs={"생계급여": 32, "의료급여": 40},
    )
    → [Judgement(program="생계급여", threshold=820556, eligible=True, margin=20556), …]
"""

from dataclasses import dataclass  # 값만 담는 간단한 클래스를 만드는 도구 (자바의 record와 비슷)

from app.eligibility.threshold import selection_threshold


@dataclass
class Judgement:
    """제도 하나에 대한 판정 결과."""

    program: str       # 제도 이름. 예: "생계급여"
    threshold: int     # 선정기준액(원/월)
    eligible: bool     # 충족 여부 = 소득인정액 ≦ 선정기준액
    margin: int        # 선정기준액 − 소득인정액. 양수 = 여유 금액, 음수 = 초과 금액


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
                threshold=threshold,
                eligible=recognized_income <= threshold,  # "이하"이므로 <= (같아도 충족)
                margin=threshold - recognized_income,
            )
        )
    return results
