"""대화 한 턴 처리 — 사용자 메시지 하나를 그래프에 넣고 챗봇의 답을 돌려준다. (API·CLI 가 같이 씀)

그래프가 되묻는 중(interrupt 로 멈춰 있음)이면 메시지를 "답"으로 넘겨 이어서 실행하고,
아니면 새 질문으로 처음(START)부터 실행한다. 어느 쪽인지는 체크포인터에 저장된 상태로 안다.
"""

from dataclasses import dataclass, field

from langgraph.types import Command

from app.chat.graph import Deps, build_graph, default_deps


@dataclass
class Reply:
    """챗봇의 답 하나."""

    text: str                                           # 화면에 보여 줄 답 (되묻는 중이면 질문)
    waiting: bool = False                               # True = 조건을 되묻는 중 (다음 메시지가 그 답)
    eligibility: list[dict] = field(default_factory=list)  # 이번 턴에 판정했으면 제도별 결과
    sources: list[dict] = field(default_factory=list)      # 답변 근거 {page, section, quote}


class Chatbot:
    """그래프 하나 + 대화별 상태(thread_id 로 구분). 서버에서는 하나만 만들어 같이 쓴다."""

    def __init__(self, deps: Deps | None = None, checkpointer=None):
        self.graph = build_graph(deps or default_deps(), checkpointer)

    def send(self, thread_id: str, message: str) -> Reply:
        """사용자 메시지 하나 → 챗봇의 답."""
        config = {"configurable": {"thread_id": thread_id}}
        if self.graph.get_state(config).next:  # 멈춰 있는 노드가 있음 = 되묻는 중
            result = self.graph.invoke(Command(resume=message), config)
        else:
            # 새 질문. 이전 턴의 답변·판정 결과는 지워서 섞이지 않게 한다 (가구 조건은 남김)
            fresh = {"messages": [{"role": "user", "content": message}], "eligibility": [], "sources": []}
            result = self.graph.invoke(fresh, config)

        if result.get("__interrupt__"):  # 그래프가 질문을 남기고 멈춤
            return Reply(text=result["__interrupt__"][0].value, waiting=True)
        return Reply(
            text=result["answer"],
            eligibility=result.get("eligibility") or [],
            sources=result.get("sources") or [],
        )
