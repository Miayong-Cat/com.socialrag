"""챗봇 그래프 (LangGraph) — 조건을 되묻고, 판정하고, 지침서 근거로 설명한다.

    START → understand ─(info: 제도 설명 질문)────────────────────────────→ retrieve → generate → END
                │ (eligibility: 받을 수 있나요?)                              ▲
                ▼                                                             │
         condition_check ─(조건이 다 모임)→ eligibility_check ────────────────┘
                │ (부족)
                ▼
          ask_condition ── interrupt(질문): 사용자의 답을 기다림
                │            (API·CLI 가 Command(resume=답)으로 다시 실행)
                └──→ understand 로 되돌아감   ← 되묻기 루프

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
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.chat.state import ChatState, HouseholdInfo, merge, missing_fields, question_for, to_household
from app.chat.understand import Understanding
from app.eligibility.household import Household
from app.rag.generator import Answer


@dataclass
class Deps:
    """그래프가 쓰는 바깥 기능 묶음."""

    understand: Callable[[list[dict], HouseholdInfo, list[str]], Understanding]  # 대화 → 의도·조건·검색어
    search: Callable[[str], list[dict]]                                         # 검색어 → 청크 목록
    judge: Callable[[Household], list[dict]]                                    # 가구 → 제도별 판정 결과
    answer: Callable[[str, list[dict], str | None], Answer]                     # 질문·청크·판정 요약 → 답변


def format_judgements(results: list[dict]) -> str:
    """판정 결과 → 사람이 읽을 표 (코드가 만든다 — 숫자를 LLM 이 옮겨 적다 틀리지 않도록)."""
    lines = ["| 급여 | 결과 | 소득인정액 | 선정기준액 |", "|---|---|---|---|"]
    for r in results:
        mark = "✅ 충족" if r["eligible"] else "❌ 미충족"
        lines.append(f"| {r['program']} | {mark} | {r['recognized_income']:,}원 | {r['threshold']:,}원 |")
    return "\n".join(lines)


def build_graph(deps: Deps, checkpointer=None):
    """그래프를 만들어 compile 한다. checkpointer 가 대화별 상태를 저장한다 (기본: 메모리)."""

    def understand_node(state: ChatState) -> dict:
        """마지막 사용자 말에서 의도·조건·검색어를 뽑아 상태에 반영한다."""
        pending = state.get("pending_fields") or []
        known = HouseholdInfo(**(state.get("household") or {}))
        result = deps.understand(state["messages"], known, pending)
        update = {"household": merge(known, result.household).model_dump()}
        if pending:
            # 되묻기에 대한 답이면 의도·원래 질문·검색어는 그대로 둔다 ("서울이요"로 검색하지 않도록)
            update["intent"] = "eligibility"
        else:
            update["intent"] = result.intent
            update["question"] = state["messages"][-1]["content"]
            update["search_query"] = result.search_query or update["question"]
        return update

    def route_after_understand(state: ChatState) -> str:
        return "condition_check" if state["intent"] == "eligibility" else "retrieve"

    def condition_check_node(state: ChatState) -> dict:
        """판정에 필요한 조건 중 아직 모르는 것을 찾는다."""
        return {"pending_fields": missing_fields(HouseholdInfo(**state["household"]))}

    def route_after_check(state: ChatState) -> str:
        return "ask_condition" if state["pending_fields"] else "eligibility_check"

    def ask_condition_node(state: ChatState) -> dict:
        """부족한 조건을 묻고, 사용자의 답을 받을 때까지 그래프를 멈춘다.

        interrupt(질문) — 여기서 실행이 멈추고 질문이 호출한 쪽(API·CLI)으로 돌아간다.
        사용자가 답하면 Command(resume=답)으로 다시 실행되고, interrupt 가 그 답을 돌려준다.
        (다시 실행될 때 이 함수는 처음부터 다시 돌지만, 질문은 같은 상태로 만들므로 똑같다)
        """
        question = question_for(state["pending_fields"])
        reply = interrupt(question)
        return {"messages": [{"role": "assistant", "content": question}, {"role": "user", "content": reply}]}

    def eligibility_check_node(state: ChatState) -> dict:
        """판정 엔진으로 제도별 충족 여부를 계산한다 (LLM 아님)."""
        household = to_household(HouseholdInfo(**state["household"]))
        return {"eligibility": deps.judge(household), "pending_fields": []}

    def retrieve_node(state: ChatState) -> dict:
        """지침서에서 근거 청크를 찾는다."""
        return {"passages": deps.search(state["search_query"])}

    def generate_node(state: ChatState) -> dict:
        """근거 청크(+ 판정 결과)로 답변을 만든다. 판정 결과 표는 코드가 만들어 답변 앞에 붙인다."""
        table = format_judgements(state["eligibility"]) if state["intent"] == "eligibility" else None
        result = deps.answer(state["question"], state["passages"], table)
        reply = f"{table}\n\n{result.text}" if table else result.text
        sources = [{"page": s.page, "section": s.section, "quote": s.quote} for s in result.sources]
        return {"answer": reply, "sources": sources, "messages": [{"role": "assistant", "content": reply}]}

    graph = StateGraph(ChatState)
    graph.add_node("understand", understand_node)
    graph.add_node("condition_check", condition_check_node)
    graph.add_node("ask_condition", ask_condition_node)
    graph.add_node("eligibility_check", eligibility_check_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "understand")
    graph.add_conditional_edges("understand", route_after_understand, ["condition_check", "retrieve"])
    graph.add_conditional_edges("condition_check", route_after_check, ["ask_condition", "eligibility_check"])
    graph.add_edge("ask_condition", "understand")  # 되묻기 루프
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

    def answer(question: str, passages: list[dict], facts: str | None) -> Answer:
        # 상태에는 DB 객체 대신 dict 를 저장하므로, generator 가 읽는 모양(GuideChunk)으로 되돌린다
        return generate(question, [GuideChunk(**p) for p in passages], facts=facts)

    return Deps(understand=understand, search=search_passages, judge=judge, answer=answer)
