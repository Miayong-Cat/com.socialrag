"""선정기준액 계산 테스트 (대상: app/eligibility/threshold.py).

기대값은 전부 2026 사업안내에 인쇄된 숫자다 (tests/guide_2026.py).

실행:
    pytest tests/test_threshold.py
"""

import pytest

from app.eligibility.threshold import selection_threshold
from tests.guide_2026 import MEDIAN_2026, PDF_TABLE, PROGRAMS


# parametrize → 아래 테스트를 PDF_TABLE 의 급여 4종마다 한 번씩, 총 4번 실행한다.
@pytest.mark.parametrize("program", PDF_TABLE)
def test_threshold_matches_pdf_table(program):
    """계산한 선정기준액 28칸(4종 × 7인)이 지침서 표와 1원도 다르지 않아야 한다."""
    calculated = [
        selection_threshold(MEDIAN_2026, PROGRAMS[program], size) for size in range(1, 8)
    ]
    assert calculated == PDF_TABLE[program]


def test_8_person_household():
    """p.14·p.78: 8인 기준 중위소득 10,474,348원, 8인 생계급여 3,351,791원."""
    # 비율 100% = 기준 중위소득 그 자체
    assert selection_threshold(MEDIAN_2026, 100, 8) == 10_474_348
    assert selection_threshold(MEDIAN_2026, 32, 8) == 3_351_791


def test_9_person_household_keeps_adding_step():
    """9인은 7인 기준에 (7인 − 6인) 차이를 두 번 더한 값이어야 한다."""
    step = 3_044_848 - 2_737_905  # 7인 − 6인 생계급여
    assert selection_threshold(MEDIAN_2026, 32, 9) == 3_044_848 + step * 2


def test_household_size_must_be_positive():
    """가구원 수 0명은 말이 안 되므로 에러."""
    with pytest.raises(ValueError):
        selection_threshold(MEDIAN_2026, 32, 0)
