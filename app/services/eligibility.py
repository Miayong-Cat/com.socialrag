"""판정 서비스 — DB에서 기준 숫자를 꺼내 판정 엔진을 부르고, 계산 내역까지 붙여 돌려준다.

판정 API(app/routes/eligibility.py)와 챗봇(app/chat/)이 같이 쓴다.
    1. median_incomes   → 그 연도의 기준 중위소득 1~7인
    2. welfare_programs → 그 연도의 제도 목록 (중위소득 대비 비율이 있는 제도만)
    3. judge_household  → 제도별 소득인정액 계산 + 판정 (app/eligibility/)

그 연도의 기준 중위소득이 DB에 없으면 LookupError (API는 404로 바꿔 돌려준다).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.eligibility.asset import asset_conversion
from app.eligibility.household import Household
from app.eligibility.income import income_evaluation
from app.eligibility.judge import judge_household
from app.eligibility.threshold import TABLE_MAX_SIZE
from app.models import MedianIncome, WelfareProgram
from app.schemas import ProgramJudgement


def load_median_incomes(db: Session, year: int) -> dict[int, int]:
    """그 연도의 기준 중위소득 {가구원 수: 금액}. 1~7인이 다 있지 않으면 LookupError."""
    rows = db.scalars(select(MedianIncome).where(MedianIncome.year == year)).all()
    incomes = {row.household_size: row.amount for row in rows}
    if any(size not in incomes for size in range(1, TABLE_MAX_SIZE + 1)):
        raise LookupError(f"{year}년 기준 중위소득이 DB에 없습니다. (python -m ingestion.load_criteria 로 적재)")
    return incomes


def load_programs(db: Session, year: int) -> list[WelfareProgram]:
    """그 연도의 제도 목록 (id 순). 중위소득 대비 비율이 없는 제도는 이 방식으로 판정할 수 없어 뺀다."""
    return db.scalars(
        select(WelfareProgram)
        .where(WelfareProgram.updated_year == year, WelfareProgram.max_income_ratio.is_not(None))
        .order_by(WelfareProgram.id)
    ).all()


def judge(db: Session, household: Household, year: int) -> list[ProgramJudgement]:
    """가구 하나를 그 연도의 모든 제도에 대해 판정한다. 결과는 제도 id 순서."""
    median_incomes = load_median_incomes(db, year)
    programs = load_programs(db, year)

    # {제도 이름: 비율} — 판정 엔진은 DB 객체가 아니라 숫자만 받는다.
    judgements = judge_household(household, median_incomes, {p.name: p.max_income_ratio for p in programs})

    # 계산 내역(소득평가액·재산 환산액)을 같이 싣는다. 재산 환산액은 제도와 무관해 한 번만 계산.
    asset = asset_conversion(household)
    return [
        ProgramJudgement(
            program=j.program,
            income_ratio=p.max_income_ratio,
            income_evaluation=income_evaluation(household, j.program),
            asset_conversion=asset,
            recognized_income=j.recognized_income,
            threshold=j.threshold,
            eligible=j.eligible,
            margin=j.margin,
            source_document=p.source_document,
            source_page=p.source_page,
        )
        for p, j in zip(programs, judgements)  # judge_household 는 넣은 순서대로 돌려준다
    ]
