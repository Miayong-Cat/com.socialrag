"""판정 API — 가구 정보를 받아 제도별 수급 가능 여부를 계산해 돌려준다.

| 메서드 | 경로              | 하는 일 | 성공 코드 |
|--------|-------------------|---------|-----------|
| POST   | /api/eligibility  | 판정    | 200       |

이 파일은 "DB에서 숫자 꺼내기 + 판정 엔진 부르기"만 한다. 계산은 전부 app/eligibility/ 가 맡는다.
    1. median_incomes   → 그 연도의 기준 중위소득 1~7인
    2. welfare_programs → 그 연도의 제도 목록 (중위소득 대비 비율이 있는 제도만)
    3. judge_household  → 제도별 소득인정액 계산 + 판정

그 연도의 기준 중위소득이 DB에 없으면 404 (적재 스크립트를 먼저 실행해야 함).
요청 본문이 형식에 안 맞으면 422 (app/schemas.py 검증).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.eligibility.asset import asset_conversion
from app.eligibility.income import income_evaluation
from app.eligibility.judge import judge_household
from app.eligibility.threshold import TABLE_MAX_SIZE
from app.models import MedianIncome, WelfareProgram
from app.schemas import EligibilityRequest, EligibilityResponse, ProgramJudgement

router = APIRouter(prefix="/api/eligibility", tags=["eligibility"])


def load_median_incomes(db: Session, year: int) -> dict[int, int]:
    """그 연도의 기준 중위소득 {가구원 수: 금액}. 1~7인이 다 있지 않으면 404."""
    rows = db.scalars(select(MedianIncome).where(MedianIncome.year == year)).all()
    incomes = {row.household_size: row.amount for row in rows}
    if any(size not in incomes for size in range(1, TABLE_MAX_SIZE + 1)):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"{year}년 기준 중위소득이 DB에 없습니다. (python -m ingestion.load_criteria 로 적재)",
        )
    return incomes


def load_programs(db: Session, year: int) -> list[WelfareProgram]:
    """그 연도의 제도 목록 (id 순). 중위소득 대비 비율이 없는 제도는 이 방식으로 판정할 수 없어 뺀다."""
    return db.scalars(
        select(WelfareProgram)
        .where(WelfareProgram.updated_year == year, WelfareProgram.max_income_ratio.is_not(None))
        .order_by(WelfareProgram.id)
    ).all()


@router.post("", response_model=EligibilityResponse)
def judge_eligibility(request: EligibilityRequest, db: Session = Depends(get_db)):
    """판정: 가구 정보로 그 연도의 모든 제도에 대해 충족 여부와 계산 내역을 돌려준다."""
    median_incomes = load_median_incomes(db, request.year)
    programs = load_programs(db, request.year)
    household = request.to_household()

    # {제도 이름: 비율} — 판정 엔진은 DB 객체가 아니라 숫자만 받는다.
    judgements = judge_household(
        household, median_incomes, {p.name: p.max_income_ratio for p in programs}
    )

    # 계산 내역(소득평가액·재산 환산액)을 응답에 같이 싣는다. 재산 환산액은 제도와 무관해 한 번만 계산.
    asset = asset_conversion(household)
    results = [
        ProgramJudgement(
            program=j.program,
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
    return EligibilityResponse(year=request.year, household_size=household.size, results=results)
