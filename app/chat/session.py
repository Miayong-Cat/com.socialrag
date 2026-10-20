"""대화 한 턴 처리 — 사용자 메시지 하나를 그래프에 넣고 챗봇의 답을 돌려준다. (API·CLI 가 같이 씀)

그래프가 되묻는 중(interrupt 로 멈춰 있음)이면 메시지를 "답"으로 넘겨 이어서 실행하고,
아니면 새 질문으로 처음(START)부터 실행한다. 어느 쪽인지는 체크포인터에 저장된 상태로 안다.

턴마다 하는 일:
    - 위기 안내(notice)가 있으면 답 맨 앞에 붙인다 (학대·긴급 생계 신호 — app/chat/crisis.py)
    - 응답 시간·판정 결과 등을 ai_search_logs 에 기록한다 (app/services/search_log.py)
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from langgraph.types import Command

from app.chat.graph import Deps, build_graph, default_deps


@dataclass
class Reply:
    """챗봇의 답 하나."""

    text: str                                           # 화면에 보여 줄 답 (되묻는 중이면 질문)
    waiting: bool = False                               # True = 조건을 되묻는 중 (다음 메시지가 그 답)
    crisis: str = ""                                    # 감지된 위기 신호 종류 ("" = 없음)
    eligibility: list[dict] = field(default_factory=list)  # 이번 턴에 판정했으면 제도별 결과
    sources: list[dict] = field(default_factory=list)      # 답변 근거 {page, section, quote}


def default_log(**fields) -> None:
    """기본 로그 기록: DB 의 ai_search_logs (import 를 늦춰 테스트에서 DB 를 건드리지 않게)."""
    from app.services.search_log import record

    record(**fields)


class Chatbot:
    """그래프 하나 + 대화별 상태(thread_id 로 구분). 서버에서는 하나만 만들어 같이 쓴다."""

    def __init__(self, deps: Deps | None = None, checkpointer=None, log: Callable[..., None] = default_log):
        self.graph = build_graph(deps or default_deps(), checkpointer)
        self.log = log  # 테스트에서는 기록을 목록에 모으는 가짜를 넣는다

    def send(self, thread_id: str, message: str) -> Reply:
        """사용자 메시지 하나 → 챗봇의 답."""
        started = time.perf_counter()
        config = {"configurable": {"thread_id": thread_id}}
        if self.graph.get_state(config).next:  # 멈춰 있는 노드가 있음 = 되묻는 중
            result = self.graph.invoke(Command(resume=message), config)
        else:
            # 새 질문. 이전 턴의 검색·판정 결과는 지워서 섞이지 않게 한다 (가구 조건은 남김)
            fresh = {"messages": [{"role": "user", "content": message}], "eligibility": [], "passages": [], "sources": []}
            result = self.graph.invoke(fresh, config)

        reply = self._to_reply(result)
        self.log(
            thread_id=thread_id,
            question=message,
            intent=None if reply.crisis == "suicide" else result.get("intent"),
            crisis=reply.crisis or None,
            retrieved_doc_count=0 if reply.waiting else len(result.get("passages") or []),
            response_time_ms=round((time.perf_counter() - started) * 1000),
            waiting=reply.waiting,
            missing_fields_count=len(result.get("pending_fields") or []) if reply.waiting else 0,
            eligibility_result={r["program"]: r["eligible"] for r in reply.eligibility} or None,
        )
        return reply

    @staticmethod
    def _to_reply(result: dict) -> Reply:
        """그래프 실행 결과 → Reply. 위기 안내(notice)는 답 맨 앞에 붙인다."""
        crisis = result.get("crisis") or ""
        notice = result.get("notice") or ""
        if result.get("__interrupt__"):  # 그래프가 질문을 남기고 멈춤
            text, waiting, eligibility, sources = result["__interrupt__"][0].value, True, [], []
        else:
            text, waiting = result["answer"], False
            eligibility, sources = result.get("eligibility") or [], result.get("sources") or []
        if notice:
            text = f"{notice}\n\n{text}"
        return Reply(text=text, waiting=waiting, crisis=crisis, eligibility=eligibility, sources=sources)
