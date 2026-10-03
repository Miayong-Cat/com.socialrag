"""복지제도 CRUD API 테스트 (대상: app/routes/welfare.py).

DB·클라이언트 준비는 conftest.py 가 해 준다 — 인자 이름 client 로 받아 쓴다.
client.post / get / put / delete → 실제 HTTP 요청처럼 API를 호출하고 응답을 받는다.

실행:
    pytest tests/test_welfare_api.py
"""

# 여러 테스트가 같이 쓰는 요청 본문 예시 (생계급여)
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
    """등록하면 201과 id를 받고, 그 id로 다시 조회하면 같은 내용이 나와야 한다."""
    created = client.post("/api/welfare", json=SAMPLE)
    assert created.status_code == 201
    program_id = created.json()["id"]

    fetched = client.get(f"/api/welfare/{program_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "생계급여"
    assert fetched.json()["household_types"] == ["1인", "2인"]  # JSON 컬럼의 리스트가 그대로 저장되는지


def test_list(client):
    """두 개 등록하면 목록에 등록한 순서(id 순)대로 나와야 한다."""
    client.post("/api/welfare", json=SAMPLE)
    # {**SAMPLE, "name": …} → SAMPLE 을 복사하면서 일부 칸만 바꾼 새 딕셔너리
    client.post("/api/welfare", json={**SAMPLE, "name": "의료급여", "max_income_ratio": 40})

    names = [p["name"] for p in client.get("/api/welfare").json()]
    assert names == ["생계급여", "의료급여"]


def test_update(client):
    """수정하면 바뀐 값이 응답에 반영돼야 한다."""
    program_id = client.post("/api/welfare", json=SAMPLE).json()["id"]

    updated = client.put(f"/api/welfare/{program_id}", json={**SAMPLE, "max_income_ratio": 33})
    assert updated.status_code == 200
    assert updated.json()["max_income_ratio"] == 33


def test_delete(client):
    """삭제하면 204, 그 뒤에 조회하면 404여야 한다."""
    program_id = client.post("/api/welfare", json=SAMPLE).json()["id"]

    assert client.delete(f"/api/welfare/{program_id}").status_code == 204
    assert client.get(f"/api/welfare/{program_id}").status_code == 404


def test_not_found(client):
    """없는 id를 조회하면 404."""
    assert client.get("/api/welfare/999").status_code == 404


def test_validation_error(client):
    """비율이 100%를 넘으면 Pydantic 검증(app/schemas.py)에서 막혀 422."""
    response = client.post("/api/welfare", json={**SAMPLE, "max_income_ratio": 150})
    assert response.status_code == 422
