"""챗봇 그래프 테스트 (대상: app/chat/graph.py, session.py, state.py).

Claude·DB 대신 가짜 함수를 넣어 "그래프가 어느 길로 가는지"만 검증한다 (API 키·Docker 불필요).
가짜 understand 는 미리 정해 둔 Understanding 을 차례로 돌려준다 = "Claude 가 이렇게 알아들었다"고 가정.

실행:
    pytest tests/test_chat_graph.py
"""

from app.chat.graph import Deps
from app.chat.session import Chatbot
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

    def understand(self, messages, known, asked):
        return self.understandings.pop(0)

    def search(self, query):
        self.searched.append(query)
        return [{"page": 131, "section": "Ⅲ. 소득조사", "heading": "", "text": "근로소득 30% 공제"}]

    def judge(self, household):
        self.judged.append(household)
        return [{"program": "생계급여", "eligible": True, "recognized_income": 770_000, "threshold": 820_556}]

    def answer(self, question, passages, facts):
        self.answered.append((question, facts))
        return Answer(text="설명입니다.", sources=[Source(page=131, section="Ⅲ. 소득조사", quote="30% 공제")])

    def bot(self) -> Chatbot:
        return Chatbot(Deps(understand=self.understand, search=self.search, judge=self.judge, answer=self.answer))


def u(intent, query="검색어", **household):
    return Understanding(intent=intent, household=HouseholdInfo(**household), search_query=query)


def test_info_question_skips_eligibility():
    """제도 설명 질문: 조건을 묻지 않고 바로 검색 → 답변. 검색은 바꿔 쓴 검색어로 한다."""
    fake = Fake([u("info", query="근로소득 공제 기준")])
    reply = fake.bot().send("t", "일해서 번 돈은 얼마나 빼주나요?")

    assert not reply.waiting
    assert reply.text == "설명입니다."
    assert fake.searched == ["근로소득 공제 기준"]
    assert fake.judged == []
    assert reply.sources == [{"page": 131, "section": "Ⅲ. 소득조사", "quote": "30% 공제"}]


def test_asks_missing_conditions_then_judges():
    """판정 질문: 부족한 조건을 되묻고(루프), 다 모이면 판정 → 판정표 + 설명."""
    fake = Fake([
        u("eligibility", query="생계급여 선정기준", size=1),           # 1턴: 1인 가구라는 것만 앎
        u("eligibility", region="서울", earned_income=1_100_000),        # 답 1: 지역·소득
        u("info", housing=0, general=0, financial=0, car_full_rate=0, debt=0),  # 답 2: 재산 없음 (intent 는 무시돼야 함)
    ])
    bot = fake.bot()

    first = bot.send("t", "혼자 사는데 생계급여 받을 수 있나요?")
    assert first.waiting
    assert first.text == question_for(["region", "income", "assets"])

    second = bot.send("t", "서울이고 월 110만원 벌어요")
    assert second.waiting
    assert second.text == question_for(["assets"])  # 남은 것만 다시 물음

    third = bot.send("t", "재산은 없어요")
    assert not third.waiting
    assert third.eligibility[0]["program"] == "생계급여"
    assert third.text.startswith("| 급여 | 결과 |")          # 판정표는 코드가 만들어 앞에 붙임
    assert "✅ 충족 | 770,000원 | 820,556원" in third.text

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
