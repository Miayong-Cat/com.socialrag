"""충족 여부 판정 테스트 (대상: app/eligibility/judge.py).

기대값은 전부 2026 사업안내에 인쇄된 숫자다 (tests/guide_2026.py).

실행:
    pytest tests/test_judge.py
"""

import pytest

from app.eligibility.judge import judge
from tests.guide_2026 import MEDIAN_2026, PROGRAMS


def test_boundary_is_inclusive():
    """p.13 예시: 1인 생계급여는 소득인정액이 820,556원보다 같거나 작아야 한다.

    경계값 바로 위·아래를 확인한다: 820,556원(같음) → 충족, 820,557원(1원 초과) → 미충족.
    """
    at_limit = judge(1, 820_556, MEDIAN_2026, {"생계급여": 32})[0]    # [0] → 결과 목록의 첫 번째
    over_limit = judge(1, 820_557, MEDIAN_2026, {"생계급여": 32})[0]

    assert at_limit.eligible and at_limit.margin == 0
    assert not over_limit.eligible and over_limit.margin == -1


def test_judge_all_programs():
    """1인 가구, 소득인정액 110만원 → 생계(82만)·의료(102만) ✗, 주거(123만)·교육(128만) ✓"""
    results = {r.program: r.eligible for r in judge(1, 1_100_000, MEDIAN_2026, PROGRAMS)}
    assert results == {"생계급여": False, "의료급여": False, "주거급여": True, "교육급여": True}


# (가구원 수, 소득인정액) 잘못된 조합 2가지를 각각 실행: 가구원 0명 / 소득 음수
@pytest.mark.parametrize("size, income", [(0, 0), (1, -1)])
def test_invalid_input(size, income):
    """잘못된 입력은 조용히 넘기지 않고 ValueError 를 내야 한다."""
    with pytest.raises(ValueError):
        judge(size, income, MEDIAN_2026, PROGRAMS)
