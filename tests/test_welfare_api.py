"""복지제도 CRUD API 테스트. (DB·클라이언트 준비는 conftest.py)

실행:
    pytest
"""

SAMPLE = {
    "name": "생계급여",
    "category": "기초생활보장",
    "max_income_ratio": 32,
    "household_types": ["1인", "2인"],
    "source_document": "2026 국민기초생활보장 사업안내",
    "source_page": 14,
    "updated_year": 2026,
}


def test_create_and_get(client):
    created = client.post("/api/welfare", json=SAMPLE)
    assert created.status_code == 201
    program_id = created.json()["id"]

    fetched = client.get(f"/api/welfare/{program_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "생계급여"
    assert fetched.json()["household_types"] == ["1인", "2인"]


def test_list(client):
    client.post("/api/welfare", json=SAMPLE)
    client.post("/api/welfare", json={**SAMPLE, "name": "의료급여", "max_income_ratio": 40})

    names = [p["name"] for p in client.get("/api/welfare").json()]
    assert names == ["생계급여", "의료급여"]


def test_update(client):
    program_id = client.post("/api/welfare", json=SAMPLE).json()["id"]

    updated = client.put(f"/api/welfare/{program_id}", json={**SAMPLE, "max_income_ratio": 33})
    assert updated.status_code == 200
    assert updated.json()["max_income_ratio"] == 33


def test_delete(client):
    program_id = client.post("/api/welfare", json=SAMPLE).json()["id"]

    assert client.delete(f"/api/welfare/{program_id}").status_code == 204
    assert client.get(f"/api/welfare/{program_id}").status_code == 404


def test_not_found(client):
    assert client.get("/api/welfare/999").status_code == 404


def test_validation_error(client):
    """비율이 100%를 넘으면 Pydantic 검증에서 막힌다."""
    response = client.post("/api/welfare", json={**SAMPLE, "max_income_ratio": 150})
    assert response.status_code == 422
