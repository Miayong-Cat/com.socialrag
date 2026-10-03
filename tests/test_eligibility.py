"""판정 엔진 테스트. 기대값은 전부 2026 사업안내에 인쇄된 숫자다."""

import pytest

from app.eligibility.rules import judge, selection_threshold

# p.14 기준 중위소득 (1~7인)
MEDIAN_2026 = {
    1: 2_564_238, 2: 4_199_292, 3: 5_359_036, 4: 6_494_738,
    5: 7_556_719, 6: 8_555_952, 7: 9_515_150,
}
PROGRAMS = {"생계급여": 32, "의료급여": 40, "주거급여": 48, "교육급여": 50}

# p.14 급여별 선정기준표 (1~7인)
PDF_TABLE = {
    "생계급여": [820_556, 1_343_773, 1_714_892, 2_078_316, 2_418_150, 2_737_905, 3_044_848],
    "의료급여": [1_025_695, 1_679_717, 2_143_614, 2_597_895, 3_022_688, 3_422_381, 3_806_060],
    "주거급여": [1_230_834, 2_015_660, 2_572_337, 3_117_474, 3_627_225, 4_106_857, 4_567_272],
    "교육급여": [1_282_119, 2_099_646, 2_679_518, 3_247_369, 3_778_360, 4_277_976, 4_757_575],
}


@pytest.mark.parametrize("program", PDF_TABLE)
def test_threshold_matches_pdf_table(program):
    """계산한 선정기준액 28칸이 지침서 표와 1원도 다르지 않아야 한다."""
    calculated = [
        selection_threshold(MEDIAN_2026, PROGRAMS[program], size) for size in range(1, 8)
    ]
    assert calculated == PDF_TABLE[program]


def test_8_person_household():
    """p.14·p.78: 8인 기준 중위소득 10,474,348원, 8인 생계급여 3,351,791원."""
    assert selection_threshold(MEDIAN_2026, 100, 8) == 10_474_348
    assert selection_threshold(MEDIAN_2026, 32, 8) == 3_351_791


def test_9_person_household_keeps_adding_step():
    step = 3_044_848 - 2_737_905  # 7인 − 6인 생계급여
    assert selection_threshold(MEDIAN_2026, 32, 9) == 3_044_848 + step * 2


def test_boundary_is_inclusive():
    """p.13 예시: 1인 생계급여는 소득인정액이 820,556원보다 같거나 작아야 한다."""
    at_limit = judge(1, 820_556, MEDIAN_2026, {"생계급여": 32})[0]
    over_limit = judge(1, 820_557, MEDIAN_2026, {"생계급여": 32})[0]

    assert at_limit.eligible and at_limit.margin == 0
    assert not over_limit.eligible and over_limit.margin == -1


def test_judge_all_programs():
    """1인 가구, 소득인정액 110만원 → 생계·의료 ✗, 주거·교육 ✓"""
    results = {r.program: r.eligible for r in judge(1, 1_100_000, MEDIAN_2026, PROGRAMS)}
    assert results == {"생계급여": False, "의료급여": False, "주거급여": True, "교육급여": True}


@pytest.mark.parametrize("size, income", [(0, 0), (1, -1)])
def test_invalid_input(size, income):
    with pytest.raises(ValueError):
        judge(size, income, MEDIAN_2026, PROGRAMS)
