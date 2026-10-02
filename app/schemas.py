"""API 요청/응답 형식. (자바로 치면 DTO + @Valid)

타입과 Field 조건만 적으면 FastAPI가 자동으로 검증하고, 틀리면 422 에러를 돌려준다.
"""

from pydantic import BaseModel, ConfigDict, Field


class WelfareProgramCreate(BaseModel):
    """등록·수정 요청 본문."""

    name: str = Field(min_length=1, examples=["생계급여"])
    category: str = Field(min_length=1, examples=["기초생활보장"])
    min_age: int | None = Field(default=None, ge=0)
    max_age: int | None = Field(default=None, ge=0)
    max_income_ratio: float | None = Field(default=None, gt=0, le=100, examples=[32])
    max_asset_amount: int | None = Field(default=None, ge=0)
    household_types: list[str] = Field(default_factory=list)
    source_document: str = Field(min_length=1, examples=["2026 국민기초생활보장 사업안내"])
    source_page: int | None = Field(default=None, ge=1)
    updated_year: int = Field(ge=2000, le=2100, examples=[2026])


class WelfareProgramResponse(WelfareProgramCreate):
    """응답 본문 = 요청 내용 + id."""

    model_config = ConfigDict(from_attributes=True)  # DB 객체 → 응답으로 바로 변환

    id: int
