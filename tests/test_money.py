"""금액 × 비율 계산 테스트 (대상: app/eligibility/money.py).

실행:
    pytest tests/test_money.py
"""

from app.eligibility.money import rate_floor, rate_round


def test_rate_floor_is_exact_where_float_is_not():
    """41,000 × 48.3% = 19,803 정확히. float 로는 19,802.999… → 버리면 1원 모자람 (비율이 소수일 때의 1원 오차)."""
    assert int(41_000 * 48.3 / 100) == 19_802          # float 의 문제 (이 테스트가 왜 있는지)
    assert rate_floor(41_000, 48.3) == 19_803


def test_rate_round_is_half_up():
    """원 단위 사사오입 — 0.5 는 항상 올림 (파이썬 round 의 은행가 반올림이 아님)."""
    assert rate_round(5, 50) == 3                       # 2.5 → 3 (round(2.5) 는 2)
    assert rate_round(2_564_238, 32) == 820_556         # 1인 생계급여 선정기준액 (p.14)
