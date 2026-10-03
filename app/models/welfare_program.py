"""welfare_programs 테이블 — 복지제도 하나 = 한 줄. (자바로 치면 JPA @Entity)

읽는 법:
    name: Mapped[str]               → NOT NULL 문자열 컬럼
    min_age: Mapped[int | None]     → NULL 허용 정수 컬럼 (| None = 비어 있어도 됨)
    mapped_column(primary_key=True) → 기본키(PK)

누가 쓰나:
    - app/routes/welfare.py         복지제도 CRUD API
    - ingestion/load_criteria.py    지침서의 급여 4종을 적재
"""

from sqlalchemy import JSON  # 리스트·딕셔너리를 그대로 저장할 수 있는 컬럼 타입
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WelfareProgram(Base):
    """복지제도 하나. (테이블: welfare_programs)

    판정 엔진이 바로 쓸 수 있도록 선정기준을 칸별로 나눠 저장한다.
    금액(원)은 저장하지 않고 "기준 중위소득 대비 %"만 저장한다.
    → 실제 금액은 판정할 때 median_incomes 테이블 × 이 비율로 계산 (app/eligibility/threshold.py)
    """

    __tablename__ = "welfare_programs"  # DB에 만들어질 실제 테이블 이름

    id: Mapped[int] = mapped_column(primary_key=True)  # 자동 증가 번호 (1, 2, 3 …)
    name: Mapped[str]                                # 제도 이름. 예: "생계급여"
    category: Mapped[str]                            # 분류. 예: "기초생활보장"
    min_age: Mapped[int | None]                      # 최소 나이 (나이 조건 없으면 None)
    max_age: Mapped[int | None]                      # 최대 나이 (나이 조건 없으면 None)
    max_income_ratio: Mapped[float | None]           # 기준 중위소득 대비 % 이하. 예: 32 → 32% 이하
    max_asset_amount: Mapped[int | None]             # 재산 기준액(원). 조건 없으면 None
    # 대상 가구 유형. 빈 리스트 [] = 제한 없음. 예: ["1인", "2인"]
    household_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_document: Mapped[str]                     # 근거 문서. 예: "2026 국민기초생활보장 사업안내"
    source_page: Mapped[int | None]                  # 근거 쪽번호 (PDF 쪽 기준)
    updated_year: Mapped[int]                        # 기준 연도 (기준은 매년 바뀜)
