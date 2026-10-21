"""챗봇 그래프 (LangGraph) — 위기 신호를 살피고, 조건을 되묻고, 판정하고, 지침서 근거로 설명한다.

    START → crisis_check ─(자살·자해 신호)→ crisis_handler → END      상담 전화 안내만 (일반 흐름 중단)
                │ (그 밖: 학대·긴급 생계는 안내를 붙이고 계속)
                ▼
            understand ─(info: 제도 설명 질문)────────────────────────→ retrieve → generate → END
                │ (eligibility: 받을 수 있나요?)                          ▲
                ▼                                                         │
         condition_check ─(조건이 다 모임)→ eligibility_check ────────────┘
                │ (부족)          └─(MAX_ASKS 번 물어도 답 없음)→ give_up → END   필요한 조건 안내
                ▼                    (공제 유형은 가정하고 판정 — 답변에 "가정함")
          ask_condition ── interrupt(질문): 사용자의 답을 기다림
                │            (API·CLI 가 Command(resume=답)으로 다시 실행)
                └──→ crisis_check 로 되돌아감   ← 되묻기 루프 (답에도 위기 신호가 있는지 다시 살핌)
                                                  답 대신 새 질문을 하면(new_question) 되묻기를 그만두고 그 질문으로

왜 체인이 아니라 그래프인가:
    조건이 부족하면 되묻고, 답을 받아 다시 확인하는 "되돌아가는 화살표"가 필요하다.
    한 방향으로만 흐르는 체인으로는 이 루프를 표현할 수 없다.

노드가 쓰는 바깥 기능(LLM·DB)은 Deps 로 주입한다.
    실제 실행: default_deps() — Claude + PostgreSQL
    테스트:    가짜 함수 — API 키·DB 없이 그래프 흐름만 검증 (tests/test_chat_graph.py)
"""

from collections.abc import Callable
from dataclasses import dataclass

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.chat.crisis import detect
from app.chat.format import compose, format_assumptions, format_basis, format_judgements, give_up_message
from app.chat.state import (
    ASSUMABLE,
    MAX_ASKS,
    ChatState,
    HouseholdInfo,
    merge,
    missing_fields,
    question_for,
    to_household,
)
from app.chat.understand import Understanding
from app.eligibility.household import Household
from app.rag.generator import Answer


@dataclass
class Deps:
    """그래프가 쓰는 바깥 기능 묶음."""

    understand: Callable[[list[dict], HouseholdInfo, list[str]], Understanding]  # 대화 → 의도·조건·검색어
    search: Callable[[str], list[dict]]                                         # 검색어 → 청크 목록
    judge: Callable[[Household], list[dict]]                                    # 가구 → 제도별 판정 결과
    answer: Callable[..., Answer]  # (질문, 청크, 판정 요약, on_text=글 조각 콜백) → 답변


def build_graph(deps: Deps, checkpointer=None):
    """그래프를 만들어 compile 한다. checkpointer 가 대화별 상태를 저장한다 (기본: 메모리)."""

    def crisis_check_node(state: ChatState) -> dict:
        """마지막 사용자 말에 위기 신호가 있는지 규칙으로 살핀다 (모든 사용자 메시지마다)."""
        crisis = detect(state["messages"][-1]["content"])
        if crisis is None:
            return {"crisis": "", "notice": ""}
        notice = crisis.message if crisis.level == "notice" else ""
        return {"crisis": crisis.category, "notice": notice}

    def route_after_crisis(state: ChatState) -> str:
        # 신호가 있는데 붙일 안내(notice)가 없다 = "stop" 단계 위기
        return "crisis_handler" if state["crisis"] and not state["notice"] else "understand"

    def crisis_handler_node(state: ChatState) -> dict:
        """자살·자해 신호: 일반 흐름 대신 상담 전화를 안내하고 끝낸다.

        되묻는 중이었어도 되묻기를 끝낸다 (pending_fields 를 비움) — 남겨 두면 다음 새 질문이 조건 답으로 처리된다.
        """
        message = detect(state["messages"][-1]["content"]).message
        return {"answer": message, "sources": [], "pending_fields": [], "ask_counts": {},
                "messages": [{"role": "assistant", "content": message}]}

    def understand_node(state: ChatState) -> dict:
        """마지막 사용자 말에서 의도·조건·검색어를 뽑아 상태에 반영한다."""
        pending = state.get("pending_fields") or []
        known = HouseholdInfo(**(state.get("household") or {}))
        result = deps.understand(state["messages"], known, pending)
        update = {"household": merge(known, result.household).model_dump()}
        if pending and not result.new_question:
            # 되묻기에 대한 답이면 의도·원래 질문·검색어는 그대로 둔다 ("서울이요"로 검색하지 않도록)
            update["intent"] = "eligibility"
        else:
            # 새 질문 — 되묻던 중에 답 대신 다른 것을 물었으면 되묻기를 그만두고 그 질문으로 간다 (사용자가 갇히지 않게)
            update |= {"intent": result.intent, "question": state["messages"][-1]["content"], "pending_fields": [], "ask_counts": {}}
            update["search_query"] = result.search_query or update["question"]
        return update

    def route_after_understand(state: ChatState) -> str:
        return "condition_check" if state["intent"] == "eligibility" else "retrieve"

    def condition_check_node(state: ChatState) -> dict:
        """판정에 필요한 조건 중 아직 모르는 것을 찾는다.

        MAX_ASKS 번 물어도 답을 못 들은 조건은 더 묻지 않는다:
            가정해도 되는 조건(ASSUMABLE — 공제 유형)은 불리한 쪽으로 가정하고 판정 (답변에 "가정함" 표시)
            그 밖의 조건은 판정을 멈추고 안내 (give_up)
        """
        counts = state.get("ask_counts") or {}
        missing = missing_fields(HouseholdInfo(**state["household"]))
        assumed = [f for f in missing if f in ASSUMABLE and counts.get(f, 0) >= MAX_ASKS]
        return {"pending_fields": [f for f in missing if f not in assumed], "assumed": assumed}

    def route_after_check(state: ChatState) -> str:
        if not state["pending_fields"]:
            return "eligibility_check"
        counts = state.get("ask_counts") or {}
        return "give_up" if any(counts.get(f, 0) >= MAX_ASKS for f in state["pending_fields"]) else "ask_condition"

    def give_up_node(state: ChatState) -> dict:
        """같은 조건을 MAX_ASKS 번 물어도 답을 못 들음 — 되묻기를 끝내고 무엇이 필요한지 안내한다."""
        counts = state.get("ask_counts") or {}
        message = give_up_message([f for f in state["pending_fields"] if counts.get(f, 0) >= MAX_ASKS])
        return {"answer": message, "sources": [], "pending_fields": [], "ask_counts": {},
                "messages": [{"role": "assistant", "content": message}]}

    def ask_condition_node(state: ChatState) -> dict:
        """부족한 조건을 묻고, 사용자의 답을 받을 때까지 그래프를 멈춘다.

        interrupt(질문) — 여기서 실행이 멈추고 질문이 호출한 쪽(API·CLI)으로 돌아간다.
        사용자가 답하면 Command(resume=답)으로 다시 실행되고, interrupt 가 그 답을 돌려준다.
        (다시 실행될 때 이 함수는 처음부터 다시 돌지만, 질문은 같은 상태로 만들므로 똑같다)
        """
        question = question_for(state["pending_fields"])
        reply = interrupt(question)
        counts = state.get("ask_counts") or {}
        return {
            "messages": [{"role": "assistant", "content": question}, {"role": "user", "content": reply}],
            "ask_counts": counts | {f: counts.get(f, 0) + 1 for f in state["pending_fields"]},  # 물어본 횟수
        }

    def eligibility_check_node(state: ChatState) -> dict:
        """판정 엔진으로 제도별 충족 여부를 계산한다 (LLM 아님)."""
        household = to_household(HouseholdInfo(**state["household"]))
        return {"eligibility": deps.judge(household), "pending_fields": [], "ask_counts": {}}

    def retrieve_node(state: ChatState) -> dict:
        """지침서에서 근거 청크를 찾는다."""
        return {"passages": deps.search(state["search_query"])}

    def generate_node(state: ChatState) -> dict:
        """근거 청크(+ 판정 결과)로 답변을 만든다.

        판정표·계산 근거·출처·면책 안내는 코드가 만들어 붙이고(app/chat/format.py), Claude 는 설명만 쓴다.

        스트리밍(Chatbot.stream): 위기 안내·판정표를 먼저 보내고, Claude 의 설명은 써지는 대로 보낸다.
        get_stream_writer() 는 stream_mode="custom" 으로 실행할 때만 실제로 보내고, invoke 일 때는 아무것도 안 한다.
        """
        write = get_stream_writer()
        judgements = state["eligibility"] if state["intent"] == "eligibility" else None
        assumed = state.get("assumed") if judgements else None
        facts = "\n".join(p for p in (format_judgements(judgements), format_basis(judgements), format_assumptions(assumed)) if p) if judgements else None
        head = [p for p in (state.get("notice"), judgements and format_judgements(judgements), judgements and format_basis(judgements),
                            format_assumptions(assumed)) if p]
        if head:
            write("\n\n".join(head) + "\n\n")
        result = deps.answer(state["question"], state["passages"], facts, on_text=write)
        sources = [{"page": s.page, "section": s.section, "quote": s.quote} for s in result.sources]
        reply = compose(result.text, sources, judgements, assumed)
        return {"answer": reply, "sources": sources, "messages": [{"role": "assistant", "content": reply}]}

    graph = StateGraph(ChatState)
    graph.add_node("crisis_check", crisis_check_node)
    graph.add_node("crisis_handler", crisis_handler_node)
    graph.add_node("understand", understand_node)
    graph.add_node("condition_check", condition_check_node)
    graph.add_node("ask_condition", ask_condition_node)
    graph.add_node("give_up", give_up_node)
    graph.add_node("eligibility_check", eligibility_check_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "crisis_check")
    graph.add_conditional_edges("crisis_check", route_after_crisis, ["crisis_handler", "understand"])
    graph.add_edge("crisis_handler", END)
    graph.add_conditional_edges("understand", route_after_understand, ["condition_check", "retrieve"])
    graph.add_conditional_edges("condition_check", route_after_check, ["ask_condition", "give_up", "eligibility_check"])
    graph.add_edge("give_up", END)
    graph.add_edge("ask_condition", "crisis_check")  # 되묻기 루프 (답도 위기 신호부터 살핌)
    graph.add_edge("eligibility_check", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)

    return graph.compile(checkpointer=checkpointer or InMemorySaver())


def default_deps() -> Deps:
    """실제로 쓰는 기능: Claude(이해·답변) + PostgreSQL(검색·판정)."""
    from app.chat.understand import understand
    from app.config import YEAR
    from app.database import SessionLocal
    from app.models import GuideChunk
    from app.rag.generator import generate
    from app.rag.retriever import search
    from app.services import eligibility

    def search_passages(query: str) -> list[dict]:
        with SessionLocal() as db:
            chunks = search(db, query)
        return [{"page": c.page, "section": c.section, "heading": c.heading, "text": c.text} for c in chunks]

    def judge(household: Household) -> list[dict]:
        with SessionLocal() as db:
            return [r.model_dump() for r in eligibility.judge(db, household, YEAR)]

    def answer(question: str, passages: list[dict], facts: str | None, on_text=None) -> Answer:
        # 상태에는 DB 객체 대신 dict 를 저장하므로, generator 가 읽는 모양(GuideChunk)으로 되돌린다
        return generate(question, [GuideChunk(**p) for p in passages], facts=facts, on_text=on_text)

    return Deps(understand=understand, search=search_passages, judge=judge, answer=answer)
