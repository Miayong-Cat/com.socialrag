"""판정 엔진의 입력 형식 — "판정할 가구"를 어떤 정보로 표현하는지 정의한다.

지침서 서식(p.451 「소득인정액 산정결과」)의 [소득 금액]·[재산 가액] 칸을 그대로 따랐다.
    소득: 근로·사업소득 / 그 밖의 소득(재산소득·이전소득 등)
    재산: 주거용재산 / 일반재산 / 금융재산 / 자동차 / 부채

금액 단위는 모두 원. 소득은 "월" 금액, 재산은 "현재 가액".

사용 예:
    Household(
        size=1,
        region=Region.SEOUL,
        earners=[Earner(monthly_income=1_000_000)],   # 일반 근로자 1명, 월 100만원
        housing=50_000_000,                            # 사는 집 전세보증금 5천만원
    )
"""

from dataclasses import dataclass, field  # 값만 담는 클래스를 간단히 만드는 도구
from enum import Enum  # 정해진 선택지 중 하나만 고르게 하는 타입 (오타 방지)


class Region(Enum):
    """거주 지역 구분. 기본재산액·주거용재산 한도액이 지역마다 다르다 (p.160, p.191)."""

    SEOUL = "서울"
    GYEONGGI = "경기"
    METRO = "광역·세종·창원"   # 광역시, 세종특별자치시, 창원시
    OTHER = "그 외 지역"


class WorkDeduction(Enum):
    """근로·사업소득 공제 유형 (p.131~132). 소득이 있는 사람마다 하나를 고른다.

    여러 유형에 해당하면 공제액이 가장 큰 쪽을 고르면 된다 (지침서: "가장 유리한 하나의 항목").
    공제율 숫자는 app/eligibility/standards.py 의 WORK_DEDUCTION_RULES 에 있다.
    """

    # 일반 수급자 — 생계·주거·교육급여에서만 30% 공제, 의료급여는 공제 없음
    GENERAL = "일반"
    # 임신 중이거나 출산 후 6개월 미만 여성, 사회복무요원·상근예비역, 행정인턴 — 모든 급여 30%
    FLAT_30 = "30% 공제"
    # 65세 이상, 등록장애인, 북한이탈주민(특례기간), 35세 이상 초·중·고등학생 — 20만원 + 나머지 30%
    BASE_200K = "20만원 + 30%"
    # 34세 이하, 대학생 — 60만원 + 나머지 30%
    YOUTH = "60만원 + 30%"
    # 등록장애인의 장애인·정신질환자 직업재활사업 참여소득 — 20만원 + 나머지 50%
    VOCATIONAL = "20만원 + 50%"


@dataclass
class Earner:
    """근로·사업소득이 있는 가구원 한 명. (공제가 사람마다 다르게 적용되므로 사람 단위로 받는다)"""

    monthly_income: int                                   # 월 근로·사업소득(원)
    deduction: WorkDeduction = WorkDeduction.GENERAL      # 공제 유형. 생략하면 일반 수급자


@dataclass
class Household:
    """판정할 가구 하나.

    "직접 계산해서 넣어야 하는 칸"이 있다 — 지침서의 세부 규칙이 너무 많아 아직 자동 계산하지 않는 부분:
        household_expenses : 가구특성별 지출비용 (장애인 의료비, 양육비 등. p.126~130)
        housing            : 주택 임차보증금은 보증금의 95%로 평가해서 넣는다 (p.164)
        general            : 일반재산 환산율이 적용되는 자동차(생업용 등)는 여기에 포함 (p.192)
        car_full_rate      : 소득환산율 100%가 적용되는 자동차의 가액만 넣는다
        debt               : 재산에서 빼 주는 부채로 확인된 금액만 넣는다 (p.186~190)
    """

    size: int                                             # 가구원 수
    region: Region                                        # 거주 지역
    earners: list[Earner] = field(default_factory=list)   # 근로·사업소득자 목록 (없으면 빈 리스트)
    other_income: int = 0          # 그 밖의 월 소득: 재산소득·이전소득 등 — 근로소득공제를 받지 않는 소득
    household_expenses: int = 0    # 가구특성별 지출비용(월) — 소득에서 빼 주는 금액
    housing: int = 0               # 주거용재산: 실제로 사는 집(자가 또는 임차보증금)
    general: int = 0               # 일반재산: 토지·건물·사는 집이 아닌 주택 등
    financial: int = 0             # 금융재산: 예금·적금·주식·보험 등
    car_full_rate: int = 0         # 소득환산율 100% 자동차 가액
    debt: int = 0                  # 부채
