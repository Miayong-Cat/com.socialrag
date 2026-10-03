"""API 요청/응답 형식. (자바로 치면 DTO + @Valid)

app/models/ 와의 차이:
    app/models/ = DB에 저장되는 모양 (테이블)
    schemas.py = API로 주고받는 JSON 모양 (+ 입력값 검증 규칙)

타입과 Field 조건만 적으면 FastAPI가 자동으로 검증하고, 틀리면 422 에러를 돌려준다.

Field 조건 읽는 법:
    min_length=1 → 빈 문자열 "" 금지
    ge=0         → 0 이상 (greater than or equal)
    gt=0         → 0 초과 (greater than)
    le=100       → 100 이하 (less than or equal)
    examples=[…] → Swagger(/docs) 화면에 보여줄 예시 값 (검증과는 무관)
"""

from pydantic import BaseModel, ConfigDict, Field


class WelfareProgramCreate(BaseModel):
    """복지제도 등록(POST)·수정(PUT) 요청 본문.

    default=None 이 붙은 칸은 생략 가능, 없는 칸은 필수.
    """

    name: str = Field(min_length=1, examples=["생계급여"])
    category: str = Field(min_length=1, examples=["기초생활보장"])
    min_age: int | None = Field(default=None, ge=0)  # 나이는 음수 불가
    max_age: int | None = Field(default=None, ge=0)
    # 비율은 0% 초과 ~ 100% 이하만 허용 (150 같은 값은 422 에러)
    max_income_ratio: float | None = Field(default=None, gt=0, le=100, examples=[32])
    max_asset_amount: int | None = Field(default=None, ge=0)
    # default_factory=list → 생략하면 빈 리스트 [] (요청마다 새 리스트를 만들어 서로 섞이지 않음)
    household_types: list[str] = Field(default_factory=list)
    source_document: str = Field(min_length=1, examples=["2026 국민기초생활보장 사업안내"])
    source_page: int | None = Field(default=None, ge=1)  # 쪽번호는 1부터
    updated_year: int = Field(ge=2000, le=2100, examples=[2026])  # 오타 방지용 범위


class WelfareProgramResponse(WelfareProgramCreate):
    """응답 본문 = 요청 내용 + id. (WelfareProgramCreate 를 상속해서 칸을 그대로 물려받음)"""

    # from_attributes=True → DB 객체(WelfareProgram)를 그대로 넘겨도 이 형식으로 변환해 준다.
    #   덕분에 라우터에서 "return program" 만 해도 JSON 응답이 된다.
    model_config = ConfigDict(from_attributes=True)

    id: int  # DB가 자동으로 붙인 번호
