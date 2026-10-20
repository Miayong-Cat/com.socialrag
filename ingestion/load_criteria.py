"""[적재 3/4] criteria JSON → DB (welfare_programs, median_incomes 테이블).

extract_criteria.py 가 만든 JSON 파일을 읽어 DB에 넣는다.
같은 연도로 여러 번 실행해도 중복이 생기지 않는다(있으면 덮어씀).

사용법:
    python -m ingestion.load_criteria
읽는 파일:
    data/processed/criteria_2026.json   (app/config.py 의 CRITERIA_JSON_PATH)
저장 위치:
    app/config.py 의 DATABASE_URL (Docker로 띄운 PostgreSQL — 먼저 docker compose up -d)
"""

import json
import sys

from sqlalchemy import delete, select  # DELETE / SELECT 쿼리를 파이썬 코드로 만드는 함수
from sqlalchemy.orm import Session

from app.config import CRITERIA_JSON_PATH
from app.database import SessionLocal, create_tables
from app.models import MedianIncome, WelfareProgram

# 이번에 넣는 제도들의 공통 정보
CATEGORY = "기초생활보장"
SOURCE_DOCUMENT = "{year} 국민기초생활보장 사업안내"  # {year} 자리에 연도를 끼워 넣어 사용
SOURCE_PAGE = 14  # 선정기준표가 있는 PDF 쪽번호 (extract_criteria.PAGE_NO 와 같은 쪽)


def load_median_incomes(db: Session, criteria: dict) -> None:
    """기준 중위소득을 median_incomes 테이블에 넣는다.

    지침서 표의 1~7인만 저장한다. 8인 이상은 판정 엔진이 계산한다(app/eligibility/threshold.py).
    중복 방지: 같은 연도 데이터를 먼저 전부 지우고 새로 넣는다.
    """
    year = criteria["year"]
    # JSON의 키는 문자열("1")이므로 DB 컬럼 타입에 맞게 정수(1)로 바꾼다.
    amounts = {int(size): amount for size, amount in criteria["median_income"]["by_household"].items()}

    # DELETE FROM median_incomes WHERE year = 2026
    db.execute(delete(MedianIncome).where(MedianIncome.year == year))
    for size, amount in amounts.items():
        db.add(MedianIncome(year=year, household_size=size, amount=amount))


def load_programs(db: Session, criteria: dict) -> None:
    """급여 4종을 welfare_programs 테이블에 제도로 등록한다.

    금액은 저장하지 않고 비율만 저장한다 (금액 = 기준 중위소득 × 비율, 판정 엔진이 계산).
    중복 방지: 같은 이름·같은 연도 제도가 이미 있으면 새로 만들지 않고 그 줄을 고친다.
    (id가 바뀌지 않도록 지우고 다시 넣는 대신 수정한다)
    """
    year = criteria["year"]
    for name, benefit in criteria["benefits"].items():
        # SELECT * FROM welfare_programs WHERE name = '생계급여' AND updated_year = 2026
        # scalar() → 결과 한 개를 꺼냄. 없으면 None
        program = db.scalar(
            select(WelfareProgram).where(
                WelfareProgram.name == name, WelfareProgram.updated_year == year
            )
        )
        if program is None:  # 처음 넣는 제도면 새로 만듦
            program = WelfareProgram(name=name, updated_year=year)
            db.add(program)
        # 새로 만든 경우든 기존 것이든 아래 값으로 맞춘다.
        program.category = CATEGORY
        program.max_income_ratio = benefit["percent_of_median"]
        program.household_types = []  # 빈 리스트 = 가구 유형 제한 없음
        program.source_document = SOURCE_DOCUMENT.format(year=year)
        program.source_page = SOURCE_PAGE


def load(db: Session, criteria: dict) -> None:
    """기준 중위소득 + 제도를 한 번에 적재하고 commit 한다.

    둘 다 끝난 뒤 마지막에 한 번만 commit 하므로, 중간에 에러가 나면 아무것도 저장되지 않는다.
    (테스트에서도 이 함수를 직접 불러 쓴다 — tests/test_load_criteria.py)
    """
    load_median_incomes(db, criteria)
    load_programs(db, criteria)
    db.commit()


def main():
    """JSON 읽기 → 테이블 준비 → 적재 → 결과 출력."""
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 터미널 한글 깨짐 방지
    criteria = json.loads(CRITERIA_JSON_PATH.read_text(encoding="utf-8"))

    create_tables()  # 서버를 한 번도 안 켰어도 테이블이 있도록 (없는 것만 만듦)
    with SessionLocal() as db:  # 블록이 끝나면 세션이 자동으로 닫힘
        load(db, criteria)
        # 확인용으로 적재 결과를 다시 읽어 온다.
        programs = db.scalars(select(WelfareProgram).order_by(WelfareProgram.id)).all()
        incomes = db.scalars(select(MedianIncome).where(MedianIncome.year == criteria["year"])).all()

    print(f"적재 완료: 기준 중위소득 {len(incomes)}건, 복지제도 {len(programs)}건")
    for p in programs:
        # :g → 32.0 을 32 로 보기 좋게 출력
        print(f"  {p.id}. {p.name}  중위소득 {p.max_income_ratio:g}% 이하  ({p.source_document} p.{p.source_page})")


# 이 파일을 직접 실행했을 때만 main() 을 부른다.
if __name__ == "__main__":
    main()
