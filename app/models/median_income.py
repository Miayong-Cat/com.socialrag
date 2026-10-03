"""median_incomes 테이블 — 연도·가구원 수별 기준 중위소득. (자바로 치면 JPA @Entity)

기준 중위소득 = 보건복지부가 매년 고시하는 "가구 소득의 중간값" (원/월).
급여별 선정기준액은 이 값 × 비율(%)로 계산한다 (app/eligibility/threshold.py).

누가 쓰나:
    - ingestion/load_criteria.py    지침서 p.14 표의 1~7인 값을 적재
"""

from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MedianIncome(Base):
    """연도·가구원 수별 기준 중위소득(원/월). (테이블: median_incomes)

    PK가 (year, household_size) 두 칸이다 → "2026년 4인 가구" 같은 조합이 한 줄.
    지침서 표에 있는 1~7인만 저장하고, 8인 이상은 판정 엔진이 계산한다(지침서 p.78 규칙).
    """

    __tablename__ = "median_incomes"  # DB에 만들어질 실제 테이블 이름

    year: Mapped[int] = mapped_column(primary_key=True)            # 기준 연도. 예: 2026
    household_size: Mapped[int] = mapped_column(primary_key=True)  # 가구원 수: 1 ~ 7
    amount: Mapped[int]                                            # 기준 중위소득(원/월). 예: 2564238
