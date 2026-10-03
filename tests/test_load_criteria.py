"""criteria JSON → DB 적재 테스트."""

from sqlalchemy import select

from app.models import MedianIncome, WelfareProgram
from ingestion.load_criteria import load

# 실제 2026 값 중 일부만 사용 (7개 가구 전부 넣는 대신 1·7인만 확인)
CRITERIA = {
    "year": 2026,
    "median_income": {
        "by_household": {"1": 2564238, "7": 9515150},
        "increment_per_extra_person": 959198,
    },
    "benefits": {
        "생계급여": {"percent_of_median": 32},
        "의료급여": {"percent_of_median": 40},
    },
}


def test_load(db):
    load(db, CRITERIA)

    programs = db.scalars(select(WelfareProgram).order_by(WelfareProgram.id)).all()
    assert [(p.name, p.max_income_ratio) for p in programs] == [("생계급여", 32), ("의료급여", 40)]
    assert programs[0].source_document == "2026 국민기초생활보장 사업안내"


def test_median_incomes(db):
    load(db, CRITERIA)

    assert db.get(MedianIncome, (2026, 7)).amount == 9_515_150
    assert db.get(MedianIncome, (2026, 8)) is None  # 8인 이상은 저장하지 않고 계산


def test_reload_does_not_duplicate(db):
    load(db, CRITERIA)
    load(db, CRITERIA)

    assert len(db.scalars(select(WelfareProgram)).all()) == 2
    assert len(db.scalars(select(MedianIncome)).all()) == 2  # 1·7인
