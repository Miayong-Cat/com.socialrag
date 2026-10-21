"""웹 화면 테스트 (대상: frontend/, app/routes/search.py).

- ApiClient 가 실제 FastAPI 앱(메모리 DB)과 주고받는 모양이 맞는지
- Streamlit 화면이 API 응답을 제대로 그리는지 — streamlit.testing 의 AppTest 로 브라우저 없이 실행,
  API 는 가짜로 바꿔 끼운다 (서버·Claude·DB 불필요)

실행:
    pytest tests/test_frontend.py
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from frontend.api_client import ApiClient, ApiError
from tests.test_eligibility_api import loaded  # noqa: F401 — fixture (2026 기준 숫자 적재)

APP = str(Path(__file__).resolve().parent.parent / "frontend" / "streamlit_app.py")


@pytest.fixture
def api(client):
    """실제 서버 대신 TestClient(FastAPI 앱 + 메모리 DB)로 요청을 보내는 ApiClient."""
    api = ApiClient()
    api.http = client
    return api


# ── ApiClient ↔ API ─────────────────────────────────────────


def test_client_judge(api, loaded):  # noqa: F811
    data = api.judge({"size": 1, "region": "서울", "earners": [{"monthly_income": 1_100_000, "deduction": "일반"}]})
    assert {r["program"]: r["eligible"] for r in data["results"]} == {
        "생계급여": True, "의료급여": False, "주거급여": True, "교육급여": True,
    }


def test_client_error_message(api):
    """API 에러는 화면에 보여 줄 문장을 담은 ApiError 로 바뀐다."""
    with pytest.raises(ApiError, match="404"):
        api.judge({"size": 1, "region": "서울"})  # 기준 중위소득 미적재 → 404


def test_client_server_down():
    api = ApiClient("http://127.0.0.1:9")  # 아무것도 없는 포트
    assert not api.is_up()
    with pytest.raises(ApiError, match="연결할 수 없습니다"):
        api.search("근로소득")


def test_search_route(api, monkeypatch):
    chunk = SimpleNamespace(page=131, section="Ⅲ. 소득조사", heading="4) 근로를 유인하기 위한 요인", text="30% 공제")
    monkeypatch.setattr("app.routes.search.search", lambda db, q, k: [chunk] * k)
    assert api.search("근로소득 공제", k=2) == [
        {"page": 131, "section": "Ⅲ. 소득조사", "heading": "4) 근로를 유인하기 위한 요인", "text": "30% 공제"}
    ] * 2


# ── Streamlit 화면 ──────────────────────────────────────────

JUDGED = {
    "program": "생계급여", "income_ratio": 32, "income_evaluation": 770_000, "asset_conversion": 0,
    "recognized_income": 770_000, "threshold": 820_556, "eligible": True, "margin": 50_556,
    "source_document": "2026 국민기초생활보장 사업안내", "source_page": 14,
}


@pytest.fixture
def fake_api(monkeypatch):
    """화면이 부르는 API 를 가짜로. 불린 기록을 calls 에 남긴다."""
    calls = []

    def chat_stream(self, message, thread_id=None):
        calls.append(("chat", message, thread_id))
        if thread_id is None:  # 되묻기: 글 조각 없이 완성본만
            yield {"type": "done", "thread_id": "t1", "reply": "가구원은 몇 명인가요?", "waiting": True, "eligibility": [], "sources": []}
            return
        yield {"type": "delta", "text": "| 급여 | 결과 |"}
        yield {"type": "done", "thread_id": "t1", "reply": "| 급여 | 결과 |\n|---|---|\n| 생계급여 | ✅ 충족 |", "waiting": False,
               "eligibility": [JUDGED], "sources": []}

    def judge(self, household):
        calls.append(("judge", household))
        return {"year": 2026, "household_size": household["size"], "results": [JUDGED]}

    monkeypatch.setattr(ApiClient, "is_up", lambda self: True)
    monkeypatch.setattr(ApiClient, "chat_stream", chat_stream)
    monkeypatch.setattr(ApiClient, "judge", judge)
    monkeypatch.setattr(ApiClient, "search", lambda self, q, k=5: [{"page": 131, "section": "Ⅲ", "heading": "", "text": "30% 공제"}] * k)
    return calls


def run(at: AppTest) -> AppTest:
    at.run(timeout=30)
    assert not at.exception, at.exception
    return at


def test_chat_keeps_thread(fake_api):
    """되묻기 → 답 → 판정. 두 번째 메시지는 첫 응답의 thread_id 로 보낸다."""
    at = run(AppTest.from_file(APP))
    at.chat_input[0].set_value("혼자 사는데 받을 수 있나요?")
    run(at)
    assert any(m.value == "가구원은 몇 명인가요?" for m in at.markdown)
    at.chat_input[0].set_value("1명이고 서울, 소득·재산 없어요")
    run(at)

    assert [c[2] for c in fake_api if c[0] == "chat"] == [None, "t1"]
    assert len(at.session_state.messages) == 4
    assert at.session_state.messages[-1]["eligibility"] == [JUDGED]


def test_example_button_sends_question(fake_api):
    at = run(AppTest.from_file(APP))
    at.button(key="example-0").click()
    run(at)
    assert fake_api[0][:2] == ("chat", "혼자 사는데 생계급여 받을 수 있나요?")


def test_calculator_converts_units(fake_api):
    """만원 입력 → 원, 전·월세 보증금은 95%, 소득 없으면 earners 비움."""
    at = run(AppTest.from_file(APP))
    at.number_input(key="size").set_value(2)
    at.selectbox(key="region").set_value("경기")
    at.number_input(key="housing").set_value(5000)   # 5천만원
    at.checkbox(key="rented").check()
    at.number_input(key="financial").set_value(300)
    next(b for b in at.button if b.label == "판정하기").click()  # 폼 제출 버튼
    run(at)

    _, household = next(c for c in fake_api if c[0] == "judge")
    assert household["size"] == 2 and household["region"] == "경기"
    assert household["housing"] == 47_500_000          # 5천만 × 95%
    assert household["financial"] == 3_000_000
    assert household["earners"] == []
    assert at.metric[0].value == "충족"


def test_search_tab(fake_api):
    at = run(AppTest.from_file(APP))
    at.text_input(key="query").set_value("근로소득 공제")
    at.number_input(key="k").set_value(3)
    run(at)
    assert len(at.expander) == 3 and at.expander[0].label.startswith("1. p.131")


def test_chat_error_is_shown_and_not_recorded(fake_api, monkeypatch):
    """API 실패(예: 키 오류 503): 에러를 보여 주고, 실패한 질문은 기록에 남기지 않는다."""
    def fail(self, message, thread_id=None):
        raise ApiError("[503] Claude API 키가 없거나 잘못됐습니다")
        yield  # 제너레이터로 만들기 위한 줄 (실행되지 않음)

    monkeypatch.setattr(ApiClient, "chat_stream", fail)
    at = run(AppTest.from_file(APP))
    at.chat_input[0].set_value("받을 수 있나요?")
    run(at)
    assert "503" in at.error[0].value
    assert at.session_state.messages == []
