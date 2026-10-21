"""금액 × 비율 계산 — 판정 엔진의 모든 "%" 계산이 같은 방법(Decimal)과 같은 끝처리 규칙을 쓰도록 한곳에 모았다.

왜 Decimal 인가:
    1.04 같은 소수는 컴퓨터의 float 로 정확히 표현되지 않아
    717,600 이어야 할 값이 717,599.9999… 가 될 수 있고, 원 미만을 버리면 1원이 틀어진다.
    Decimal(str(1.04)) 는 "1.04" 를 글자 그대로 정확한 소수로 다룬다.
    (전에는 재산 환산만 Decimal, 선정기준액·근로소득공제는 float 였다 — 비율이 소수가 되면 1원씩 어긋날 수 있었음)

끝처리 규칙:
    rate_round  원 단위 사사오입 — 선정기준액 (p.14 표가 반올림한 값)
    rate_floor  원 미만 버림     — 근로소득공제액·보증금 평가액 (지침서에서 규정을 찾지 못해 버림, 확인 필요)
    apply_rate  끝처리 없음      — 여러 값을 더한 뒤 한 번에 버릴 때 (재산 환산액, app/eligibility/asset.py)
"""

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal


def apply_rate(amount: int, percent: float) -> Decimal:
    """amount × percent% 를 오차 없이 계산한다 (끝처리 안 함)."""
    return Decimal(amount) * Decimal(str(percent)) / 100


def rate_floor(amount: int, percent: float) -> int:
    """amount × percent%, 원 미만 버림."""
    return int(apply_rate(amount, percent).to_integral_value(rounding=ROUND_FLOOR))


def rate_round(amount: int, percent: float) -> int:
    """amount × percent%, 원 단위 사사오입.

    파이썬 기본 round() 는 0.5를 짝수 쪽으로 보내는 "은행가 반올림"이라 (round(2.5) == 2)
    지침서 표와 1원씩 어긋날 수 있다 → ROUND_HALF_UP (0.5 는 항상 올림).
    """
    return int(apply_rate(amount, percent).to_integral_value(rounding=ROUND_HALF_UP))
