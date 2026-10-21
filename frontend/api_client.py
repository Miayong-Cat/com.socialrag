"""UI → FastAPI 서버 호출. 화면 코드(streamlit_app.py)가 HTTP 세부사항을 몰라도 되게 여기 모았다.

UI 는 판정 엔진·챗봇을 직접 import 하지 않고 API 로만 쓴다.
    → 화면과 서버를 따로 띄우고 따로 배포할 수 있다 (9단계 Docker)
    → API 가 바뀌면 이 파일만 고치면 된다

에러는 ApiError 하나로 바꿔 던진다 (message = 화면에 그대로 보여 줄 한국어 문장).
"""

import json
from collections.abc import Iterator

import httpx

DEFAULT_URL = "http://127.0.0.1:8000"
CHAT_TIMEOUT = 180  # 첫 질문은 임베딩 모델 로딩 + Claude 2회라 오래 걸릴 수 있음 (초)
TIMEOUT = 60


# 판정 API 가 받는 값 — 화면의 선택 목록. 화면은 서버 코드(app/)를 import 하지 않으므로 여기 적고,
# 판정 엔진의 Region·WorkDeduction 과 같은지는 tests/test_frontend.py 가 검사한다 (엔진이 바뀌면 테스트가 깨짐)
REGIONS = ["서울", "경기", "광역·세종·창원", "그 외 지역"]
DEDUCTIONS = {  # {화면에 보일 설명: API 값}
    "일반": "일반",
    "65세 이상 · 등록장애인 · 35세 이상 학생 (20만원 + 30%)": "20만원 + 30%",
    "34세 이하 · 대학생 (60만원 + 30%)": "60만원 + 30%",
    "임신 중 · 출산 6개월 미만 · 사회복무요원 (30%)": "30% 공제",
    "장애인 직업재활 참여 (20만원 + 50%)": "20만원 + 50%",
}


class ApiError(Exception):
    """API 호출 실패. str(e) 를 화면에 보여 준다."""


def raise_api_error(response: httpx.Response):
    """4xx·5xx 응답 → ApiError (FastAPI 의 detail 을 메시지로)."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = response.text
    raise ApiError(f"[{response.status_code}] {detail}")


class ApiClient:
    def __init__(self, base_url: str = DEFAULT_URL, transport: httpx.BaseTransport | None = None):
        # transport: 테스트에서 실제 서버 대신 FastAPI 앱에 바로 요청을 보낼 때 넣는다
        self.http = httpx.Client(base_url=base_url.rstrip("/"), transport=transport, timeout=TIMEOUT)

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.TimeoutException as e:
            raise ApiError("서버 응답이 너무 늦습니다. 잠시 후 다시 시도해 주세요.") from e
        except httpx.HTTPError as e:
            raise ApiError(f"API 서버에 연결할 수 없습니다 ({self.http.base_url}). `uvicorn app.main:app` 으로 서버를 켜 주세요.") from e
        if response.status_code >= 400:
            raise_api_error(response)
        return response.json()

    def is_up(self) -> bool:
        """서버가 켜져 있나 (OpenAPI 문서가 응답하나)."""
        try:
            return self.http.get("/openapi.json", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def chat(self, message: str, thread_id: str | None = None) -> dict:
        """POST /api/chat → {thread_id, reply, waiting, eligibility, sources}"""
        return self._request("POST", "/api/chat", json={"thread_id": thread_id, "message": message}, timeout=CHAT_TIMEOUT)

    def chat_stream(self, message: str, thread_id: str | None = None) -> Iterator[dict]:
        """POST /api/chat/stream → {"type": "delta", "text"} 여러 개, 마지막에 {"type": "done", ...chat 과 같은 칸}"""
        body = {"thread_id": thread_id, "message": message}
        try:
            with self.http.stream("POST", "/api/chat/stream", json=body, timeout=CHAT_TIMEOUT) as response:
                if response.status_code >= 400:
                    response.read()
                    raise_api_error(response)
                for line in response.iter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if event["type"] == "error":  # 스트리밍 도중 실패는 줄로 온다 (app/routes/chat.py)
                        raise ApiError(event["message"])
                    yield event
        except httpx.TimeoutException as e:
            raise ApiError("서버 응답이 너무 늦습니다. 잠시 후 다시 시도해 주세요.") from e
        except httpx.HTTPError as e:
            raise ApiError(f"API 서버에 연결할 수 없습니다 ({self.http.base_url}). `uvicorn app.main:app` 으로 서버를 켜 주세요.") from e

    def judge(self, household: dict) -> dict:
        """POST /api/eligibility → {year, household_size, results: [...]}"""
        return self._request("POST", "/api/eligibility", json=household)

    def search(self, query: str, k: int = 5) -> list[dict]:
        """GET /api/search → [{page, section, heading, text}]"""
        return self._request("GET", "/api/search", params={"q": query, "k": k})
