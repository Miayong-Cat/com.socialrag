"""판정 API 테스트 (대상: app/routes/eligibility.py).

DB에는 실제 적재 스크립트(ingestion/load_criteria.py 의 load)로 2026 지침서 숫자를 넣고 시작한다.
기대값은 전부 2026 사업안내에 인쇄된 숫자다 (tests/guide_2026.py).

실행:
    pytest tests/test_eligibility_api.py
"""

import pytest

from ingestion.load_criteria import load
from tests.guide_2026 import MEDIAN_2026, PROGRAMS


@pytest.fixture
def loaded(db):
    """메모리 DB에 2026 기준 중위소득 + 급여 4종을 적재한다. (client 와 같은 DB를 씀)"""
    criteria = {
        "year": 2026,
        "median_income": {"by_household": {str(k): v for k, v in MEDIAN_2026.items()}},
        "benefits": {name: {"percent_of_median": pct} for name, pct in PROGRAMS.items()},
    }
    load(db, criteria)


def by_program(response) -> dict:
    """응답 본문의 results 를 {제도 이름: 결과} 로 바꾼다."""
    return {r["program"]: r for r in response.json()["results"]}


def test_worker_one_person(client, loaded):
    """서울 1인, 일반 근로자 월 110만원, 재산 없음.

    생계급여: 110만 − 30% = 770,000 ≦ 820,556   → 충족
    의료급여: 공제 없음   1,100,000 > 1,025,695 → 미충족
    주거·교육급여: 770,000 → 충족
    """
    response = client.post(
        "/api/eligibility",
        json={"size": 1, "region": "서울", "earners": [{"monthly_income": 1_100_000}]},
    )
    assert response.status_code == 200
    results = by_program(response)

    assert list(results) == ["생계급여", "의료급여", "주거급여", "교육급여"]  # 제도 id 순서
    assert {name: r["eligible"] for name, r in results.items()} == {
        "생계급여": True, "의료급여": False, "주거급여": True, "교육급여": True,
    }

    livelihood = results["생계급여"]
    assert livelihood["income_evaluation"] == 770_000
    assert livelihood["recognized_income"] == 770_000
    assert livelihood["threshold"] == 820_556
    assert livelihood["margin"] == 50_556
    assert livelihood["source_page"] == 14

    assert results["의료급여"]["recognized_income"] == 1_100_000
    assert results["의료급여"]["margin"] == 1_025_695 - 1_100_000

    # 계산 내역: 근로소득과 급여별 공제액 (의료급여는 일반 공제 없음)
    assert livelihood["earned_income"] == results["의료급여"]["earned_income"] == 1_100_000
    assert livelihood["work_deduction"] == 330_000
    assert results["의료급여"]["work_deduction"] == 0


def test_asset_is_included(client, loaded):
    """p.191 예시1: 세종, 주거용재산 1억6,600만 + 일반재산 3천만 → 재산의 소득환산액 2,802,600원.

    소득이 없어도 재산 환산액만으로 1인 가구 모든 급여 기준(최대 1,282,119원)을 넘는다.
    """
    response = client.post(
        "/api/eligibility",
        json={"size": 1, "region": "광역·세종·창원", "housing": 166_000_000, "general": 30_000_000},
    )
    results = by_program(response)

    for r in results.values():
        assert r["asset_conversion"] == 2_802_600
        assert r["income_evaluation"] == 0
        assert r["recognized_income"] == 2_802_600
        assert not r["eligible"]


def test_eight_person_household(client, loaded):
    """p.14 주석: 8인 가구 생계급여 선정기준액은 3,351,791원 (DB에는 1~7인만 있음)."""
    response = client.post("/api/eligibility", json={"size": 8, "region": "서울"})
    assert by_program(response)["생계급여"]["threshold"] == 3_351_791


def test_youth_deduction(client, loaded):
    """34세 이하 공제: 월 100만 → 60만 + (40만 × 30%) = 72만 공제 → 소득평가액 28만 (의료급여도 같음)."""
    response = client.post(
        "/api/eligibility",
        json={
            "size": 1,
            "region": "경기",
            "earners": [{"monthly_income": 1_000_000, "deduction": "60만원 + 30%"}],
        },
    )
    results = by_program(response)
    assert results["생계급여"]["income_evaluation"] == 280_000
    assert results["의료급여"]["income_evaluation"] == 280_000


def test_no_median_income_for_year(client, loaded):
    """적재하지 않은 연도로 판정하면 404."""
    response = client.post("/api/eligibility", json={"year": 2025, "size": 1, "region": "서울"})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"size": 0, "region": "서울"},                                       # 가구원 0명
        {"size": 1, "region": "부산"},                                       # 없는 지역 구분
        {"size": 1, "region": "서울", "financial": -1},                      # 음수 금액
        {"size": 1, "region": "서울", "earners": [{"monthly_income": 1, "deduction": "없음"}]},  # 없는 공제 유형
    ],
)
def test_validation_error(client, loaded, body):
    """형식에 안 맞는 입력은 Pydantic 검증(app/schemas.py)에서 막혀 422."""
    assert client.post("/api/eligibility", json=body).status_code == 422
