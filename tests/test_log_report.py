"""로그 리포트 테스트 (대상: evals/log_report.py). DB 대신 Turn 목록을 직접 만든다.

실행:
    pytest tests/test_log_report.py
"""

from datetime import datetime, timedelta

from evals.log_report import Turn, build_report, judgement_funnel, conversations, percentile, render
from tests.test_chat_graph import Fake, u

T0 = datetime(2026, 10, 21, 9, 0)


def turn(id, thread, ms, intent="info", waiting=False, missing=0, result=None, crisis=None, docs=5):
    return Turn(
        id=id, created_at=T0 + timedelta(minutes=id), thread_id=thread, intent=intent, crisis=crisis,
        retrieved_doc_count=0 if waiting else docs, response_time_ms=ms, waiting=waiting,
        missing_fields_count=missing, eligibility_result=result,
    )


TURNS = [
    # a: 되묻기 2번 뒤 판정
    turn(1, "a", 1000, "eligibility", waiting=True, missing=3),
    turn(2, "a", 1200, "eligibility", waiting=True, missing=1),
    turn(3, "a", 9000, "eligibility", result={"생계급여": True, "의료급여": False}),
    # b: 첫 턴에 판정
    turn(4, "b", 8000, "eligibility", result={"생계급여": False, "의료급여": False}),
    # c: 되묻기 중 설명 질문으로 넘어감 → 판정 실패, 설명 답변
    turn(5, "c", 900, "eligibility", waiting=True, missing=2),
    turn(6, "c", 6000, "info"),
    # d: 위기 중단
    turn(7, "d", 50, None, crisis="suicide", docs=0),
]


def test_percentile_nearest_rank():
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50) == 5
    assert percentile([7], 95) == 7


def test_judgement_funnel():
    f = judgement_funnel(conversations(TURNS))
    assert f == {"attempts": 3, "succeeded": 2, "first_turn": 1, "avg_asks": 1.0}  # 되묻기 (2 + 0) / 2


def test_build_report():
    r = build_report(TURNS)
    assert (r["turns"], r["conversations"]) == (7, 4)
    assert r["latency_by_kind"]["되묻기"]["count"] == 3
    assert r["latency_by_kind"]["판정 + 답변"]["mean"] == 8500
    assert r["latency_by_kind"]["위기 중단"]["max"] == 50
    assert r["programs"] == {"생계급여": (1, 2), "의료급여": (0, 2)}
    assert r["missing_fields"] == {3: 1, 1: 1, 2: 1}
    assert r["crisis"] == {"suicide": 1}
    assert r["avg_docs"] == 5  # 답변 턴(3, 4, 6)만 — 되묻기·위기 중단 제외

    text = render(r, "리포트")
    assert "| 판정까지 감 | 2 (66.7%) |" in text
    assert "| 생계급여 | 1 / 2 (50.0%) |" in text


def test_empty_report():
    assert "기록이 없습니다" in render(build_report([]), "리포트")


def test_chatbot_log_fields_fit_turn():
    """챗봇이 실제로 남기는 로그 칸으로 Turn 을 만들 수 있어야 한다 (칸 이름이 어긋나면 여기서 잡힘)."""
    fake = Fake([u("eligibility", size=1), u("info", region="서울", earned_income=0, housing=0)])
    bot = fake.bot()
    bot.send("t", "혼자 사는데 받을 수 있나요?")
    bot.send("t", "서울이고 소득·재산 없어요")

    turns = [Turn(id=i, created_at=T0, **{k: v for k, v in log.items() if k != "question"}) for i, log in enumerate(fake.logs)]
    assert judgement_funnel(conversations(turns)) == {"attempts": 1, "succeeded": 1, "first_turn": 0, "avg_asks": 1}


def test_failed_turns_are_counted_separately():
    """실패한 턴: 따로 세고, 응답 시간은 '실패' 종류로, 검색 청크 평균에서는 뺀다. 판정 시도 중 실패면 시도 실패."""
    failed = Turn(id=9, created_at=T0 + timedelta(minutes=9), thread_id="e", intent=None, crisis=None,
                  retrieved_doc_count=0, response_time_ms=3000, waiting=False, missing_fields_count=0,
                  eligibility_result=None, error="APIConnectionError: Connection error.")
    asking = turn(8, "e", 1000, "eligibility", waiting=True, missing=1)
    r = build_report([*TURNS, asking, failed])

    assert r["failed"] == 1
    assert r["latency_by_kind"]["실패"]["count"] == 1
    assert r["avg_docs"] == build_report(TURNS)["avg_docs"]          # 실패 턴은 검색 평균에 안 들어감
    assert r["funnel"]["attempts"] == 4 and r["funnel"]["succeeded"] == 2  # e 의 시도는 실패로
    assert "- 실패한 턴: 1 (" in render(r, "t")


def test_suicide_notice_turn_is_not_a_stop():
    """자살 신호라도 제도 질문이라 안내만 붙이고 답한 턴(의도 있음)은 '위기 중단'이 아니라 답변 턴으로 센다."""
    notice = turn(9, "f", 7000, "info", crisis="suicide")
    r = build_report([*TURNS, notice])
    assert r["latency_by_kind"]["위기 중단"]["count"] == 1          # d 의 stop 턴만
    assert r["latency_by_kind"]["설명 답변"]["count"] == 2
