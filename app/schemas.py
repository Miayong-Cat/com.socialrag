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

from app.config import YEAR
from app.eligibility.household import Earner, Household, Region, WorkDeduction


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


# ── 판정 API (app/routes/eligibility.py) ─────────────────────
# 입력 칸은 판정 엔진의 Household(app/eligibility/household.py)와 1:1로 같다.
# 금액은 모두 원 단위. 소득은 "월" 금액, 재산은 "현재 가액".


class EarnerRequest(BaseModel):
    """근로·사업소득이 있는 가구원 한 명."""

    monthly_income: int = Field(ge=0, examples=[1_100_000])
    # Enum 은 값(한글)으로 주고받는다. 예: "일반", "60만원 + 30%" — 목록은 Swagger 화면에 나온다.
    deduction: WorkDeduction = WorkDeduction.GENERAL


class EligibilityRequest(BaseModel):
    """판정 요청 본문 = 판정할 가구 하나. 생략한 금액은 0원."""

    year: int = Field(default=YEAR, ge=2000, le=2100)  # 어느 연도 기준으로 판정할지. 생략하면 config 의 YEAR
    size: int = Field(ge=1, le=20, examples=[1])        # 가구원 수
    region: Region = Field(examples=["서울"])           # "서울" / "경기" / "광역·세종·창원" / "그 외 지역"
    earners: list[EarnerRequest] = Field(default_factory=list)
    other_income: int = Field(default=0, ge=0)          # 그 밖의 월 소득 (재산소득·이전소득 등)
    household_expenses: int = Field(default=0, ge=0)    # 가구특성별 지출비용(월)
    housing: int = Field(default=0, ge=0)               # 주거용재산 (임차보증금은 95%로 평가한 금액)
    general: int = Field(default=0, ge=0)               # 일반재산
    financial: int = Field(default=0, ge=0)             # 금융재산
    car_full_rate: int = Field(default=0, ge=0)         # 소득환산율 100% 자동차 가액
    debt: int = Field(default=0, ge=0)                  # 재산에서 빼 주는 부채

    def to_household(self) -> Household:
        """API 요청 형식 → 판정 엔진 입력 형식(Household)으로 바꾼다."""
        return Household(
            size=self.size,
            region=self.region,
            earners=[Earner(e.monthly_income, e.deduction) for e in self.earners],
            other_income=self.other_income,
            household_expenses=self.household_expenses,
            housing=self.housing,
            general=self.general,
            financial=self.financial,
            car_full_rate=self.car_full_rate,
            debt=self.debt,
        )


class ProgramJudgement(BaseModel):
    """제도 하나의 판정 결과 + 계산 내역. (나중에 챗봇이 판정 이유를 설명할 때 이 숫자를 쓴다)"""

    program: str                 # 제도 이름
    income_ratio: float          # 선정기준 = 기준 중위소득의 몇 % 이하 (예: 생계급여 32)
    income_evaluation: int       # 소득평가액 — 제도마다 다를 수 있음 (의료급여는 일반 30% 공제 없음)
    asset_conversion: int        # 재산의 소득환산액 — 모든 제도 같음
    recognized_income: int       # 소득인정액 = 소득평가액 + 재산의 소득환산액
    threshold: int               # 선정기준액
    eligible: bool               # 충족 여부 = 소득인정액 ≦ 선정기준액
    margin: int                  # 선정기준액 − 소득인정액. 양수 = 여유, 음수 = 초과
    source_document: str         # 근거 문서
    source_page: int | None      # 근거 쪽번호


class EligibilityResponse(BaseModel):
    """판정 응답 본문."""

    year: int
    household_size: int
    results: list[ProgramJudgement]  # 제도 id 순서
