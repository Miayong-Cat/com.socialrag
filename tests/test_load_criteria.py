"""criteria JSON → DB 적재 테스트 (대상: ingestion/load_criteria.py).

실제 JSON 파일이나 PDF 없이, 아래 CRITERIA 딕셔너리를 JSON 대신 넣어 load() 를 직접 호출한다.
DB 세션은 conftest.py 의 db fixture(빈 메모리 DB)를 쓴다.

실행:
    pytest tests/test_load_criteria.py
"""

from sqlalchemy import select

from app.models import MedianIncome, WelfareProgram
from ingestion.load_criteria import load

# extract_criteria.py 가 만드는 JSON과 같은 모양.
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
    """급여가 제도로 등록되고, 비율·출처 문서가 맞게 들어가야 한다."""
    load(db, CRITERIA)

    programs = db.scalars(select(WelfareProgram).order_by(WelfareProgram.id)).all()
    assert [(p.name, p.max_income_ratio) for p in programs] == [("생계급여", 32), ("의료급여", 40)]
    assert programs[0].source_document == "2026 국민기초생활보장 사업안내"


def test_median_incomes(db):
    """기준 중위소득은 표에 있는 가구원 수만 저장되고, 8인은 저장되지 않아야 한다."""
    load(db, CRITERIA)

    # db.get(테이블, (기본키1, 기본키2)) → PK가 (year, household_size) 두 칸이라 튜플로 조회
    assert db.get(MedianIncome, (2026, 7)).amount == 9_515_150
    assert db.get(MedianIncome, (2026, 8)) is None  # 8인 이상은 저장하지 않고 계산


def test_reload_does_not_duplicate(db):
    """같은 데이터를 두 번 적재해도 줄 수가 늘어나지 않아야 한다."""
    load(db, CRITERIA)
    load(db, CRITERIA)

    assert len(db.scalars(select(WelfareProgram)).all()) == 2  # 생계·의료
    assert len(db.scalars(select(MedianIncome)).all()) == 2  # 1·7인
