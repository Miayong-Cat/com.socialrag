"""DB 테이블 정의. (자바로 치면 JPA @Entity)"""

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WelfareProgram(Base):
    """복지제도 하나. 판정 엔진이 바로 쓸 수 있도록 선정기준을 칸별로 나눠 저장한다."""

    __tablename__ = "welfare_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]                                # 예: "생계급여"
    category: Mapped[str]                            # 예: "기초생활보장"
    min_age: Mapped[int | None]                      # 나이 조건 없으면 None
    max_age: Mapped[int | None]
    max_income_ratio: Mapped[float | None]           # 기준 중위소득 대비 % (예: 32)
    max_asset_amount: Mapped[int | None]             # 재산 기준액(원)
    household_types: Mapped[list[str]] = mapped_column(JSON, default=list)  # 예: ["1인", "2인"]
    source_document: Mapped[str]                     # 예: "2026 국민기초생활보장 사업안내"
    source_page: Mapped[int | None]
    updated_year: Mapped[int]                        # 기준 연도 (매년 바뀜)
