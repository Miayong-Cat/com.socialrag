"""질문 이해 테스트 (대상: app/chat/understand.py). 실제 LLM 없이 가짜 client 로 호출 순서와 실패 처리를 확인한다.

모델이 실제로 얼마나 잘 알아듣는지는 여기서 재지 않는다 — evals/eval_testset.py 의 chat 모드가 잰다.
"""

from types import SimpleNamespace as NS

from app.chat.state import HouseholdInfo
from app.chat.understand import understand

EXTRACTED = '{"intent": "info", "household": {"region": "서울"}, "search_query": "해산급여", "new_question": false}'
MESSAGES = [{"role": "user", "content": "해산급여가 뭐예요?"}]


class FakeClient:
    """client.chat(...) 을 흉내 내어 준비한 답을 차례로 돌려준다."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def chat(self, **kwargs):
        self.requests.append(kwargs)
        return NS(message=NS(content=self.replies.pop(0)))


def test_safe_message_is_extracted():
    client = FakeClient('{"self_harm_risk": false}', EXTRACTED)
    result = understand(MESSAGES, HouseholdInfo(), [], client=client)
    assert (result.self_harm_risk, result.search_query, result.household.region) == (False, "해산급여", "서울")
    assert "self_harm_risk" not in client.requests[1]["format"]["properties"]  # 위기 판단은 전용 호출로만


def test_risky_message_stops_before_extraction():
    client = FakeClient('{"self_harm_risk": true}')
    assert understand([{"role": "user", "content": "그냥 끝낼래요"}], HouseholdInfo(), [], client=client).self_harm_risk
    assert len(client.requests) == 1


def test_only_last_message_is_checked_for_risk():
    """지난 말까지 함께 보면, 위기 안내 뒤의 평범한 질문까지 계속 멈춘다."""
    client = FakeClient('{"self_harm_risk": false}', EXTRACTED)
    understand([{"role": "user", "content": "앞선 말"}, {"role": "assistant", "content": "안내"}, *MESSAGES], HouseholdInfo(), [], client=client)
    assert client.requests[0]["messages"][-1]["content"] == "해산급여가 뭐예요?"
    assert len(client.requests[0]["messages"]) == 2


def test_plain_reply_skips_risk_check_only_while_asking():
    """되묻는 중의 짧은 답("없어요")만 위기 판단을 건너뛴다 (모델이 위험으로 봐서 되묻기가 끊겼다)."""
    client = FakeClient(EXTRACTED)
    assert not understand([{"role": "user", "content": "없 어요."}], HouseholdInfo(), ["income"], client=client).self_harm_risk
    assert len(client.requests) == 1  # 조건 뽑기만


def test_plain_reply_exception_stays_narrow():
    """예외는 좁게: 되묻는 중이 아니거나, 짧은 답에 다른 말이 붙으면 위기 판단을 그대로 한다."""
    assert understand([{"role": "user", "content": "없어요"}], HouseholdInfo(), [], client=FakeClient('{"self_harm_risk": true}')).self_harm_risk
    for message in ("없어요 이제 다 끝이에요", "모르겠어요 그냥 사라지고 싶어요", "재산 없어요 살 이유도 없어요", "아니요 오늘이 마지막이에요"):
        client = FakeClient('{"self_harm_risk": true}')
        assert understand([{"role": "user", "content": message}], HouseholdInfo(), ["income"], client=client).self_harm_risk, message


def test_broken_risk_answer_counts_as_risk():
    """위기 판단 답의 형식이 깨지면 위험으로 본다 — 놓치는 쪽이 더 위험하다."""
    assert understand(MESSAGES, HouseholdInfo(), [], client=FakeClient("형식이 깨진 답")).self_harm_risk


def test_broken_extraction_falls_back_to_search():
    """조건 뽑기 답이 깨지면 조건 없이 원래 질문으로 검색만 한다."""
    result = understand(MESSAGES, HouseholdInfo(), [], client=FakeClient('{"self_harm_risk": false}', "형식이 깨진 답"))
    assert (result.intent, result.search_query, result.self_harm_risk) == ("info", "해산급여가 뭐예요?", False)
    assert result.household == HouseholdInfo()
