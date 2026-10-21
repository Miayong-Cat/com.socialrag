"""소득인정액 계산에 쓰는 2026 지침서 숫자 모음 — 숫자는 이 파일에만 적는다.

매년 지침서가 바뀌면 이 파일의 숫자만 새 지침서와 맞추면 된다.
모든 값에 근거 쪽번호(PDF 쪽 기준)를 적어 두었다.

(기준 중위소득과 급여별 비율은 PDF에서 자동 추출해 DB에 넣지만,
 아래 값들은 표가 작고 매년 몇 개만 바뀌어서 코드에 직접 적었다)
"""

from app.eligibility.household import Region, WorkDeduction

# 만원 단위 숫자를 원으로 바꿀 때 쓰는 값 (9_900 * MAN = 99,000,000원)
MAN = 10_000

# ── 재산 (p.160, p.174, p.191~192) ─────────────────────────

# 기본재산액: 기본 생활에 필요하다고 보고 소득환산에서 빼 주는 재산 (가구원 수와 무관) — p.191
BASIC_PROPERTY_DEDUCTION = {
    Region.SEOUL: 9_900 * MAN,
    Region.GYEONGGI: 8_000 * MAN,
    Region.METRO: 7_700 * MAN,
    Region.OTHER: 5_300 * MAN,
}

# 주거용재산 한도액: 이 금액까지만 주거용재산(낮은 환산율)으로 보고, 넘는 부분은 일반재산으로 본다 — p.160
HOUSING_CAP = {
    Region.SEOUL: 17_200 * MAN,
    Region.GYEONGGI: 15_100 * MAN,
    Region.METRO: 14_600 * MAN,
    Region.OTHER: 11_200 * MAN,
}

# 생활준비금: 금융재산에서 가구당 빼 주는 금액 — p.174
LIVING_RESERVE = 500 * MAN

# 재산 종류별 월 소득환산율(%) — p.192
#   예) 일반재산 4.17% → 기본재산액을 넘는 일반재산은 24개월(4.17% × 24 ≒ 100%) 안에 쓴다고 보는 것 (p.193)
CONVERSION_RATE = {
    "housing": 1.04,        # 주거용재산
    "general": 4.17,        # 일반재산
    "financial": 6.26,      # 금융재산
    "car_full_rate": 100,   # 소득환산율 100% 자동차
}

# ── 소득 (p.131~132) ──────────────────────────────────────

# 근로·사업소득 공제 규칙: {공제 유형: (먼저 빼 주는 금액, 나머지에 대한 공제율 %)}
#   예) BASE_200K = (200,000, 30) → 소득 100만원이면 20만원 + (80만원 × 30%) = 44만원 공제
WORK_DEDUCTION_RULES = {
    WorkDeduction.GENERAL: (0, 30),
    WorkDeduction.FLAT_30: (0, 30),
    WorkDeduction.BASE_200K: (20 * MAN, 30),
    WorkDeduction.YOUTH: (60 * MAN, 30),
    WorkDeduction.VOCATIONAL: (20 * MAN, 50),
}

# 일반 수급자(GENERAL)의 30% 공제가 적용되는 급여 — 의료급여는 빠져 있다 (p.131 "생계･주거･교육급여 수급(권)자")
GENERAL_DEDUCTION_PROGRAMS = {"생계급여", "주거급여", "교육급여"}
WORK_DEDUCTION_PAGE = 131  # 근로소득공제 규칙이 있는 지침서 쪽 (계산 근거 표시용)
