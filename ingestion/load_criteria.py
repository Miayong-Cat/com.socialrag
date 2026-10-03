"""[적재 3/3] criteria JSON → DB (welfare_programs, median_incomes).

같은 연도로 여러 번 실행해도 중복이 생기지 않는다(있으면 덮어씀).

사용법:
    python -m ingestion.load_criteria
"""

import json
import sys

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import MedianIncome, WelfareProgram
from ingestion.extract_criteria import OUT_PATH as CRITERIA_PATH

CATEGORY = "기초생활보장"
SOURCE_DOCUMENT = "{year} 국민기초생활보장 사업안내"
SOURCE_PAGE = 14


def load_median_incomes(db: Session, criteria: dict) -> None:
    """지침서 표의 1~7인만 저장. 8인 이상은 판정 엔진이 계산한다(app/eligibility/rules.py)."""
    year = criteria["year"]
    amounts = {int(size): amount for size, amount in criteria["median_income"]["by_household"].items()}

    db.execute(delete(MedianIncome).where(MedianIncome.year == year))
    for size, amount in amounts.items():
        db.add(MedianIncome(year=year, household_size=size, amount=amount))


def load_programs(db: Session, criteria: dict) -> None:
    """급여 4종을 제도로 등록. 금액은 저장하지 않고 비율만 저장한다(금액 = 중위소득 × 비율)."""
    year = criteria["year"]
    for name, benefit in criteria["benefits"].items():
        program = db.scalar(
            select(WelfareProgram).where(
                WelfareProgram.name == name, WelfareProgram.updated_year == year
            )
        )
        if program is None:
            program = WelfareProgram(name=name, updated_year=year)
            db.add(program)
        program.category = CATEGORY
        program.max_income_ratio = benefit["percent_of_median"]
        program.household_types = []  # 가구 유형 제한 없음
        program.source_document = SOURCE_DOCUMENT.format(year=year)
        program.source_page = SOURCE_PAGE


def load(db: Session, criteria: dict) -> None:
    load_median_incomes(db, criteria)
    load_programs(db, criteria)
    db.commit()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    criteria = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        load(db, criteria)
        programs = db.scalars(select(WelfareProgram).order_by(WelfareProgram.id)).all()
        incomes = db.scalars(select(MedianIncome).where(MedianIncome.year == criteria["year"])).all()

    print(f"적재 완료: 기준 중위소득 {len(incomes)}건, 복지제도 {len(programs)}건")
    for p in programs:
        print(f"  {p.id}. {p.name}  중위소득 {p.max_income_ratio:g}% 이하  ({p.source_document} p.{p.source_page})")


if __name__ == "__main__":
    main()
