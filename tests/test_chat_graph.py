"""챗봇 그래프 테스트 (대상: app/chat/graph.py, session.py, state.py).

Claude·DB 대신 가짜 함수를 넣어 "그래프가 어느 길로 가는지"만 검증한다 (API 키·Docker 불필요).
가짜 understand 는 미리 정해 둔 Understanding 을 차례로 돌려준다 = "Claude 가 이렇게 알아들었다"고 가정.

실행:
    pytest tests/test_chat_graph.py
"""

from app.chat.crisis import detect
from app.chat.format import ASSUMPTION_NOTES, DISCLAIMER, UNCITED_WARNING, format_basis, give_up_message
from app.chat.graph import Deps
from app.chat.session import Chatbot, Reply
from app.chat.state import HouseholdInfo, missing_fields, question_for, to_household
from app.chat.understand import Understanding
from app.eligibility.household import Region, WorkDeduction
from app.rag.generator import Answer, Source


class Fake:
    """가짜 바깥 기능 묶음. 무엇이 어떤 값으로 불렸는지 기록한다."""

    def __init__(self, understandings: list[Understanding]):
        self.understandings = list(understandings)
        self.searched: list[str] = []
        self.judged = []
        self.answered = []
        self.logs: list[dict] = []
        self.sources = [Source(page=131, section="Ⅲ. 소득조사", quote="30% 공제")]  # 가짜 Claude 가 인용한 문장

    def understand(self, messages, known, asked):
        return self.understandings.pop(0)

    def search(self, query):
        self.searched.append(query)
        return [{"page": 131, "section": "Ⅲ. 소득조사", "heading": "", "text": "근로소득 30% 공제"}]

    def judge(self, household):
        self.judged.append(household)
        return [JUDGEMENT]

    def answer(self, question, passages, facts, on_text=None):
        self.answered.append((question, facts))
        if on_text:  # 가짜 Claude 도 두 조각으로 나눠 "스트리밍"한다
            on_text("설명")
            on_text("입니다.")
        return Answer(text="설명입니다.", sources=self.sources)

    def log(self, **fields):
        self.logs.append(fields)

    def bot(self) -> Chatbot:
        deps = Deps(understand=self.understand, search=self.search, judge=self.judge, answer=self.answer)
        return Chatbot(deps, log=self.log)  # 로그도 가짜 — 실제 DB 에 쓰지 않음


# 가짜 판정 결과 하나 (app/schemas.py 의 ProgramJudgement 모양)
JUDGEMENT = {
    "program": "생계급여", "income_ratio": 32, "income_evaluation": 770_000, "asset_conversion": 0,
    "recognized_income": 770_000, "threshold": 820_556, "eligible": True, "margin": 50_556,
    "source_document": "2026 국민기초생활보장 사업안내", "source_page": 14,
}


def u(intent, query="검색어", new_question=False, **household):
    return Understanding(intent=intent, household=HouseholdInfo(**household), search_query=query, new_question=new_question)


def test_info_question_skips_eligibility():
    """제도 설명 질문: 조건을 묻지 않고 바로 검색 → 답변. 검색은 바꿔 쓴 검색어로 한다."""
    fake = Fake([u("info", query="근로소득 공제 기준")])
    reply = fake.bot().send("t", "일해서 번 돈은 얼마나 빼주나요?")

    assert not reply.waiting
    assert reply.text.startswith("설명입니다.")
    assert "p.131 [Ⅲ. 소득조사] “30% 공제”" in reply.text   # 출처 (코드가 붙임)
    assert reply.text.endswith(DISCLAIMER)                    # 면책 안내
    assert fake.searched == ["근로소득 공제 기준"]
    assert fake.judged == []
    assert reply.sources == [{"page": 131, "section": "Ⅲ. 소득조사", "quote": "30% 공제"}]


def test_asks_missing_conditions_then_judges():
    """판정 질문: 부족한 조건을 되묻고(루프), 다 모이면 판정 → 판정표 + 설명."""
    fake = Fake([
        u("eligibility", query="생계급여 선정기준", size=1),           # 1턴: 1인 가구라는 것만 앎
        u("eligibility", region="서울", earned_income=1_100_000),        # 답 1: 지역·소득
        u("info", deduction="일반", housing=0, general=0, financial=0, car_full_rate=0, debt=0),  # 답 2: 해당 없음·재산 없음 (intent 는 무시돼야 함)
    ])
    bot = fake.bot()

    first = bot.send("t", "혼자 사는데 생계급여 받을 수 있나요?")
    assert first.waiting
    assert first.text == question_for(["region", "income", "assets"])

    second = bot.send("t", "서울이고 월 110만원 벌어요")
    assert second.waiting
    assert second.text == question_for(["deduction", "assets"])  # 남은 것만 다시 물음 (근로소득이 있어 공제 유형도)

    third = bot.send("t", "해당 사항 없고 재산은 없어요")
    assert not third.waiting
    assert third.eligibility[0]["program"] == "생계급여"
    assert third.text.startswith("| 급여 | 결과 |")          # 판정표는 코드가 만들어 앞에 붙임
    assert "✅ 충족 | 770,000원 | 820,556원" in third.text
    assert format_basis([JUDGEMENT]) in third.text             # 계산 근거

    household = fake.judged[0]
    assert (household.size, household.region, household.earners[0].monthly_income) == (1, Region.SEOUL, 1_100_000)
    # 검색·답변은 되묻기 답("재산은 없어요")이 아니라 처음 질문 기준
    assert fake.searched == ["생계급여 선정기준"]
    question, facts = fake.answered[0]
    assert question == "혼자 사는데 생계급여 받을 수 있나요?"
    assert "생계급여" in facts


def test_conditions_are_kept_for_next_question():
    """같은 대화의 다음 판정 질문에서는 이미 모은 조건을 다시 묻지 않는다."""
    full = dict(size=2, region="경기", earned_income=0, housing=0, general=0, financial=0, car_full_rate=0, debt=0)
    fake = Fake([u("eligibility", **full), u("eligibility")])
    bot = fake.bot()

    bot.send("t", "부부 둘이 사는데 받을 수 있나요?")
    again = bot.send("t", "그럼 의료급여는요?")

    assert not again.waiting
    assert len(fake.judged) == 2
    assert fake.judged[1].size == 2


def test_threads_are_separate():
    """대화(thread_id)가 다르면 조건도 따로 모은다."""
    fake = Fake([u("eligibility", size=1), u("eligibility")])
    bot = fake.bot()
    bot.send("a", "받을 수 있나요?")
    reply = bot.send("b", "받을 수 있나요?")
    assert reply.text == question_for(["size", "region", "income", "assets"])


def test_missing_fields_and_to_household():
    """재산은 칸이 하나라도 채워지면 답한 것으로 보고, 모르는 금액은 0 으로 판정한다."""
    info = HouseholdInfo(size=1, region="광역·세종·창원", earned_income=1_000_000, deduction="60만원 + 30%", financial=0)
    assert missing_fields(info) == []
    household = to_household(info)
    assert household.region is Region.METRO
    assert household.earners[0].deduction is WorkDeduction.YOUTH
    assert household.housing == 0
    assert missing_fields(HouseholdInfo(size=1)) == ["region", "income", "assets"]
    # 근로소득이 있으면 공제 유형을 묻는다 (없거나 0이면 묻지 않음)
    worker = HouseholdInfo(size=1, region="서울", earned_income=1_000_000, housing=0)
    assert missing_fields(worker) == ["deduction"]
    assert missing_fields(worker.model_copy(update={"deduction": "일반"})) == []
    assert missing_fields(worker.model_copy(update={"earned_income": 0})) == []


def test_chat_api_continues_thread(client):
    """API: 첫 요청에서 받은 thread_id 로 이어 보내면 되묻기 답으로 처리된다."""
    from app.main import app
    from app.routes.chat import get_chatbot

    full = dict(region="서울", earned_income=0, housing=0, general=0, financial=0, car_full_rate=0, debt=0)
    fake = Fake([u("eligibility", **full), u("eligibility", size=3)])
    bot = fake.bot()
    app.dependency_overrides[get_chatbot] = lambda: bot

    first = client.post("/api/chat", json={"message": "받을 수 있나요?"}).json()
    assert first["waiting"] and first["reply"] == question_for(["size"])

    second = client.post("/api/chat", json={"thread_id": first["thread_id"], "message": "3명이요"}).json()
    assert not second["waiting"]
    assert second["eligibility"][0]["program"] == "생계급여"
    assert fake.judged[0].size == 3


# ── 7단계: 위기 신호 · 답변 형식 · 로그 ─────────────────────────


def test_detect_crisis_levels():
    """자살 신호는 stop, 학대·긴급 생계는 notice, 일반 질문은 None."""
    assert detect("요즘 너무 힘들어서 죽고 싶어요").level == "stop"
    assert detect("남편이 때려요").category == "abuse"
    assert detect("가정폭력 피해자도 특례가 있나요?").level == "notice"   # 제도 질문도 안내 + 답변 계속
    assert detect("며칠째 굶고 있어요").category == "livelihood"
    assert detect("당장 내일 먹을 쌀도 없어요").category == "livelihood"  # 평가셋 Q33 에서 놓쳤던 표현
    assert detect("먹을 것도 없어요").category == "livelihood"
    assert detect("생계급여 선정기준이 뭔가요?") is None


def test_suicide_signal_stops_normal_flow():
    """자살 신호: 상담 전화만 안내하고 이해·검색·판정을 하지 않는다."""
    fake = Fake([])
    reply = fake.bot().send("t", "다 끝내고 싶어요. 생계급여 받을 수 있나요?")

    assert reply.crisis == "suicide"
    assert "109" in reply.text
    assert fake.searched == [] and fake.judged == []
    assert fake.logs[0]["crisis"] == "suicide" and fake.logs[0]["intent"] is None


def test_livelihood_notice_is_prefixed_and_flow_continues():
    """긴급 생계 신호: 긴급복지지원 안내를 맨 앞에 붙이고 질문에는 그대로 답한다."""
    fake = Fake([u("info")])
    reply = fake.bot().send("t", "쌀이 떨어졌는데 어디서 도움 받을 수 있나요?")

    assert reply.crisis == "livelihood"
    assert reply.text.startswith(detect("쌀이 떨어졌어요").message)
    assert "설명입니다." in reply.text


def test_crisis_checked_in_condition_answers():
    """되묻기에 대한 답에서도 위기 신호를 살핀다 (되묻기 루프가 crisis_check 를 거침)."""
    fake = Fake([u("eligibility", size=1)])
    bot = fake.bot()
    bot.send("t", "받을 수 있나요?")
    reply = bot.send("t", "서울이고 소득은 없어요. 그냥 살기 싫어요")
    assert reply.crisis == "suicide"
    assert "109" in reply.text


def test_uncited_answer_gets_warning():
    """Claude 답변에 지침서 인용이 하나도 없으면 경고를 붙인다 (환각 방지)."""
    fake = Fake([u("info")])
    fake.sources = []
    reply = fake.bot().send("t", "기초연금은 얼마인가요?")
    assert UNCITED_WARNING in reply.text


def test_turns_are_logged():
    """턴마다 로그: 되묻기 턴은 부족한 조건 수, 판정 턴은 판정 요약·검색 문서 수."""
    fake = Fake([
        u("eligibility", size=1, region="서울"),
        u("eligibility", earned_income=0, housing=0, general=0, financial=0, car_full_rate=0, debt=0),
    ])
    bot = fake.bot()
    bot.send("t", "받을 수 있나요?")
    bot.send("t", "소득도 재산도 없어요")

    asking, judged = fake.logs
    assert (asking["waiting"], asking["missing_fields_count"], asking["eligibility_result"]) == (True, 2, None)
    assert (judged["waiting"], judged["retrieved_doc_count"]) == (False, 1)
    assert judged["eligibility_result"] == {"생계급여": True}
    assert judged["intent"] == "eligibility" and judged["response_time_ms"] >= 0


# ── 8단계: 스트리밍 ─────────────────────────────────────────


def test_stream_sends_pieces_then_reply():
    """stream: 판정표를 먼저, Claude 설명은 조각으로, 맨 끝에 send 와 같은 Reply. 되묻기 턴은 Reply 만."""
    full = dict(region="서울", earned_income=0, housing=0, general=0, financial=0, car_full_rate=0, debt=0)
    fake = Fake([u("eligibility", **full), u("eligibility", size=1)])
    bot = fake.bot()

    asking = list(bot.stream("t", "받을 수 있나요?"))
    assert len(asking) == 1 and isinstance(asking[0], Reply) and asking[0].waiting

    *pieces, reply = bot.stream("t", "1명이요")
    assert pieces[0].startswith("| 급여 |")              # 판정표가 설명보다 먼저
    assert pieces[1:] == ["설명", "입니다."]
    assert isinstance(reply, Reply) and not reply.waiting
    assert reply.text.startswith(pieces[0].rstrip())     # 완성본도 판정표로 시작
    assert len(fake.logs) == 2                           # 스트리밍도 턴마다 로그


def test_chat_stream_api(client):
    """API /api/chat/stream: NDJSON 줄 — delta 여러 개, 마지막 done 은 /api/chat 응답과 같은 칸."""
    import json

    from app.main import app
    from app.routes.chat import get_chatbot

    bot = Fake([u("info")]).bot()
    app.dependency_overrides[get_chatbot] = lambda: bot

    response = client.post("/api/chat/stream", json={"message": "근로소득 공제는?"})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    assert events[-1]["reply"].startswith("설명입니다.") and events[-1]["thread_id"]
    assert events[-1]["sources"] == [{"page": 131, "section": "Ⅲ. 소득조사", "quote": "30% 공제"}]


def test_basis_explains_work_deduction():
    """계산 근거에 급여별 근로소득공제와 근거 쪽 — 의료급여만 공제가 없는 이유도 코드가 적는다.

    (이유가 안 보이면 Claude 가 맞는 판정을 "다시 확인하라"고 의심하는 설명을 썼다)
    """
    worker = {"earned_income": 1_100_000, "asset_conversion": 0, "income_ratio": 32, "source_page": 14}
    basis = format_basis([
        worker | {"program": "생계급여", "work_deduction": 330_000, "income_evaluation": 770_000},
        worker | {"program": "의료급여", "work_deduction": 0, "income_evaluation": 1_100_000, "income_ratio": 40},
    ])
    assert "생계급여: 소득평가액 770,000원 (근로소득 1,100,000원에서 근로소득공제 330,000원을 뺌, p.131)" in basis
    assert "의료급여: 소득평가액 1,100,000원 (일반 근로소득공제 30%는 생계·주거·교육급여에만 있어 의료급여에는 적용 안 됨, p.131)" in basis
    assert "근로소득공제" not in format_basis([JUDGEMENT])  # 근로소득이 없으면 공제 설명도 없음


def test_claude_failure_is_503_not_500(client):
    """Claude API 가 실패하면(크레딧 부족·연결 실패 등) 500 대신 503 + 이유. 스트리밍은 error 줄."""
    import json

    import anthropic
    import httpx

    from app.main import app
    from app.routes.chat import get_chatbot

    def fail(*args, **kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    fake = Fake([])
    fake.understand = fail
    bot = fake.bot()
    app.dependency_overrides[get_chatbot] = lambda: bot

    response = client.post("/api/chat", json={"message": "받을 수 있나요?"})
    assert response.status_code == 503 and "Claude API 오류" in response.json()["detail"]

    events = [json.loads(line) for line in client.post("/api/chat/stream", json={"message": "받을 수 있나요?"}).text.splitlines()]
    assert events[-1]["type"] == "error" and "Claude API 오류" in events[-1]["message"]


# ── 독립 리뷰에서 찾은 상태 버그 (회귀 테스트) ─────────────────


def test_failed_turn_does_not_swallow_next_question():
    """답변 생성이 실패하면(Claude 529·연결 끊김) 노드가 남는다. 다음 메시지는 되묻기 답이 아니라 새 질문이어야 한다.

    (전에는 남은 노드를 "되묻는 중"으로 보고 resume → 새 질문은 버려지고 실패한 앞 질문이 다시 실행됐다)
    """
    fake = Fake([u("info", query="Q1"), u("info", query="Q2")])
    calls = []

    def flaky_answer(question, passages, facts, on_text=None):
        calls.append(question)
        if len(calls) == 1:
            raise RuntimeError("529 overloaded")
        return Answer(text="설명입니다.", sources=fake.sources)

    fake.answer = flaky_answer
    bot = fake.bot()
    try:
        bot.send("t", "첫 질문")
    except RuntimeError:
        pass

    reply = bot.send("t", "두 번째 질문")
    assert calls == ["첫 질문", "두 번째 질문"]
    assert fake.searched == ["Q1", "Q2"]
    assert reply.text.startswith("설명입니다.")


def test_crisis_during_asking_ends_the_asking():
    """되묻는 중에 자살 신호 → 상담 안내로 끝나고, 다음 새 질문은 조건 답이 아니라 새 질문으로 처리된다."""
    fake = Fake([u("eligibility", size=1), u("info", query="해산급여")])
    bot = fake.bot()
    assert bot.send("t", "생계급여 받을 수 있나요? 1인 가구").waiting

    crisis = bot.send("t", "죽고 싶어요")
    assert crisis.crisis == "suicide" and not crisis.waiting

    reply = bot.send("t", "아이 낳으면 받는 급여는?")
    assert not reply.waiting
    assert fake.searched == ["해산급여"]
    assert fake.answered[-1][0] == "아이 낳으면 받는 급여는?"


def test_chat_applies_deposit_rate_like_api():
    """챗봇도 전·월세 보증금을 95%로 넘긴다 — 계산기(판정 API)와 같은 가구면 같은 결과."""
    from app.schemas import EligibilityRequest

    info = HouseholdInfo(size=1, region="서울", earned_income=0, housing=120_000_000, rented=True)
    api = EligibilityRequest(size=1, region="서울", housing=120_000_000, rented=True)
    assert to_household(info).housing == api.to_household().housing == 114_000_000
    assert to_household(info.model_copy(update={"rented": False})).housing == 120_000_000


# ── 되묻기에 갇히지 않기 (2차 독립 리뷰) ─────────────────────────

WORKER = dict(size=1, region="서울", earned_income=1_100_000, housing=0, general=0, financial=0, car_full_rate=0, debt=0)


def test_unknown_deduction_is_assumed_after_two_asks():
    """공제 유형에 "모르겠어요"를 반복하면 MAX_ASKS 번만 묻고, 일반 공제로 가정해 판정 + "가정함" 안내.

    (전에는 같은 질문을 끝없이 반복했고, 매 턴 Claude 를 불렀다)
    """
    fake = Fake([u("eligibility", **WORKER), u("eligibility"), u("eligibility")])
    bot = fake.bot()
    assert bot.send("t", "서울 혼자 월 110만원, 재산 없어요").text == question_for(["deduction"])
    assert bot.send("t", "모르겠어요").text == question_for(["deduction"])   # 2번째

    judged = bot.send("t", "잘 모르겠어요")                                  # 더 묻지 않고 판정
    assert not judged.waiting and judged.eligibility
    assert fake.judged[0].earners[0].deduction is WorkDeduction.GENERAL
    assert ASSUMPTION_NOTES["deduction"] in judged.text
    assert ASSUMPTION_NOTES["deduction"] in fake.answered[0][1]              # Claude 에게도 가정했다고 알림


def test_gives_up_when_required_condition_never_answered():
    """가정할 수 없는 조건(가구원 수)은 MAX_ASKS 번 물어도 모르면 판정을 멈추고 안내 — 되묻기에 갇히지 않는다."""
    fake = Fake([u("eligibility", **{k: v for k, v in WORKER.items() if k != "size"}, deduction="일반"),
                 u("eligibility"), u("eligibility"), u("info", query="해산급여")])
    bot = fake.bot()
    assert bot.send("t", "받을 수 있나요?").waiting
    assert bot.send("t", "글쎄요").waiting

    stop = bot.send("t", "잘 모르겠어요")
    assert not stop.waiting and stop.text == give_up_message(["size"])
    assert fake.judged == []

    after = bot.send("t", "아이 낳으면 받는 급여는?")  # 다음 질문은 새 질문으로
    assert not after.waiting and fake.searched == ["해산급여"]


def test_new_question_while_asking_escapes():
    """되묻는 중에 답 대신 다른 질문을 하면(new_question) 되묻기를 그만두고 그 질문에 답한다."""
    fake = Fake([u("eligibility", size=1), u("info", query="해산급여", new_question=True)])
    bot = fake.bot()
    assert bot.send("t", "혼자 사는데 받을 수 있나요?").waiting

    reply = bot.send("t", "그런데 아이 낳으면 받는 급여는 뭐예요?")
    assert not reply.waiting
    assert fake.searched == ["해산급여"]
    assert fake.answered[-1][0] == "그런데 아이 낳으면 받는 급여는 뭐예요?"
    assert bot.graph.get_state({"configurable": {"thread_id": "t"}}).values["household"]["size"] == 1  # 모은 조건은 남음


def test_failed_turn_is_logged_and_stream_reports_error(client):
    """실패한 턴도 ai_search_logs 에 error 와 함께 기록, 스트리밍은 Claude 오류가 아니어도 error 줄로 알린다."""
    import json

    from app.main import app
    from app.routes.chat import get_chatbot

    fake = Fake([u("info"), u("info")])

    def broken_search(query):
        raise RuntimeError("DB down")

    fake.search = broken_search
    bot = fake.bot()
    try:
        bot.send("t", "질문")
    except RuntimeError:
        pass
    assert fake.logs[-1]["error"] == "RuntimeError: DB down" and fake.logs[-1]["waiting"] is False

    app.dependency_overrides[get_chatbot] = lambda: bot
    events = [json.loads(line) for line in client.post("/api/chat/stream", json={"message": "질문"}).text.splitlines()]
    assert events[-1]["type"] == "error" and "알 수 없는 오류" in events[-1]["message"]


def test_asks_rented_when_home_value_given():
    """집 가액만 듣고 자가·전월세를 모르면 묻는다 — 전세라고 하면 95%로, 끝내 모르면 자가로 가정 + 안내."""
    home = dict(WORKER, earned_income=0, housing=120_000_000)
    fake = Fake([u("eligibility", **home), u("eligibility", rented=True)])
    bot = fake.bot()
    assert bot.send("t", "서울 혼자, 소득 없고 1억2천 집에 살아요").text == question_for(["rented"])
    assert not bot.send("t", "전세예요").waiting
    assert fake.judged[0].housing == 114_000_000                       # 보증금 95%

    fake = Fake([u("eligibility", **home), u("eligibility"), u("eligibility")])
    bot = fake.bot()
    bot.send("t", "서울 혼자, 소득 없고 1억2천 집에 살아요")
    bot.send("t", "글쎄요")
    judged = bot.send("t", "모르겠어요")
    assert fake.judged[0].housing == 120_000_000                       # 자가로 가정 (100%)
    assert ASSUMPTION_NOTES["rented"] in judged.text


# ── 자원 상한 (2차 독립 리뷰) ─────────────────────────────────


def test_idle_threads_are_forgotten():
    """THREAD_TTL_SECONDS 넘게 조용한 대화는 메모리에서 지운다 — 서버를 오래 켜 둬도 대화 상태가 끝없이 쌓이지 않게."""
    from app.chat.session import THREAD_TTL_SECONDS

    now = [0.0]
    fake = Fake([u("eligibility", size=1), u("info"), u("info")])
    bot = Chatbot(Deps(understand=fake.understand, search=fake.search, judge=fake.judge, answer=fake.answer),
                  log=fake.log, clock=lambda: now[0])
    state = lambda t: bot.graph.get_state({"configurable": {"thread_id": t}}).values  # noqa: E731

    assert bot.send("old", "혼자 사는데 받을 수 있나요?").waiting
    now[0] += THREAD_TTL_SECONDS - 1
    bot.send("recent", "질문")
    assert state("old")["household"]["size"] == 1          # 아직 TTL 안 지남

    now[0] += 2                                            # old 는 TTL 초과, recent 는 아님
    bot.send("new", "질문")
    assert state("old") == {} and "old" not in bot.last_used
    assert state("recent") and state("new")


def test_message_length_is_capped(client):
    """메시지 글자 수 상한 — 긴 글 한 번이 매 턴 Claude 입력·메모리를 계속 키우지 않게."""
    from app.main import app
    from app.routes.chat import MAX_MESSAGE_CHARS, get_chatbot

    app.dependency_overrides[get_chatbot] = lambda: Fake([]).bot()
    assert client.post("/api/chat", json={"message": "가" * (MAX_MESSAGE_CHARS + 1)}).status_code == 422
    assert client.post("/api/chat/stream", json={"message": "가" * (MAX_MESSAGE_CHARS + 1)}).status_code == 422


# ── 위기 감지 오탐 (4차 독립 리뷰) ───────────────────────────


def test_suicide_word_in_program_question_is_notice_not_stop():
    """'자살예방 지원 제도'처럼 제도를 묻는 말은 109 안내를 붙이고 질문에도 답한다. 본인의 지금 마음이 드러나면 항상 멈춘다."""
    from app.chat.crisis import SUICIDE_INFO_NOTICE

    for question in ("자살예방 상담 지원 제도가 있나요?", "자살 유가족 지원 사업이 있나요?"):
        c = detect(question)
        assert (c.category, c.level) == ("suicide", "notice")
    for question in ("자살하고 싶은데 지원 제도 같은 게 있나요?", "죽고 싶어요 상담 센터 알려 주세요",
                     "요즘 자살 생각이 나요", "자해했어요 병원비 지원 되나요?"):
        assert detect(question).level == "stop", question     # 놓치지 않는 쪽은 그대로

    fake = Fake([u("info", query="자살예방 상담 지원")])
    reply = fake.bot().send("t", "자살예방 상담 지원 제도가 있나요?")
    assert reply.crisis == "suicide"
    assert reply.text.startswith(SUICIDE_INFO_NOTICE)          # 안내는 항상 맨 앞
    assert "설명입니다." in reply.text and fake.searched == ["자살예방 상담 지원"]  # 질문에도 답함
    assert fake.logs[-1]["intent"] == "info"                   # 로그: 위기 중단이 아니라 답한 턴
