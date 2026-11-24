"""로컬 LLM 연결 — Ollama(이 PC에서 돌아가는 무료 모델 서버)에 붙는 곳을 여기 한 곳에 둔다.

API 키·결제가 필요 없다. 필요한 것은 두 가지뿐:
    1) Ollama 설치 + 실행 (https://ollama.com)
    2) 모델 내려받기: ollama pull exaone3.5:7.8b  /  ollama pull gemma3:4b
"""

import httpx
import ollama

from app.config import LLM_TIMEOUT, OLLAMA_HOST

# Ollama 가 꺼져 있거나 모델이 없을 때 나는 오류들 — API 는 이걸 잡아 500 대신 503 으로 이유를 알린다
LLM_ERRORS = (ollama.ResponseError, ollama.RequestError, ConnectionError, httpx.HTTPError)


def make_client() -> ollama.Client:
    return ollama.Client(host=OLLAMA_HOST, timeout=LLM_TIMEOUT)


def describe_error(e: Exception) -> str:
    """LLM 오류 → 화면에 보여 줄 문장. 흔한 원인(서버 꺼짐·모델 없음)은 해결 방법까지 알려 준다."""
    if isinstance(e, ollama.ResponseError) and e.status_code == 404:
        return f"지금은 AI 상담을 할 수 없습니다 (로컬 LLM 모델이 없습니다. `ollama pull` 로 내려받으세요: {e.error})"
    if isinstance(e, ConnectionError | httpx.ConnectError):
        return f"지금은 AI 상담을 할 수 없습니다 (로컬 LLM 오류: Ollama 에 연결하지 못했습니다 — {OLLAMA_HOST}. Ollama 를 실행해 주세요)"
    return f"지금은 AI 상담을 할 수 없습니다 (로컬 LLM 오류: {e})"
