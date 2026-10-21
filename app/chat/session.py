"""대화 한 턴 처리 — 사용자 메시지 하나를 그래프에 넣고 챗봇의 답을 돌려준다. (API·CLI 가 같이 씀)

그래프가 되묻는 중(interrupt 로 멈춰 있음)이면 메시지를 "답"으로 넘겨 이어서 실행하고,
아니면 새 질문으로 처음(START)부터 실행한다. 어느 쪽인지는 체크포인터에 저장된 상태로 안다.

턴마다 하는 일:
    - 위기 안내(notice)가 있으면 답 맨 앞에 붙인다 (학대·긴급 생계 신호 — app/chat/crisis.py)
    - 응답 시간·판정 결과 등을 ai_search_logs 에 기록한다 (app/services/search_log.py)
"""

import time
from collections.abc import Callable, Iterator
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

    def is_waiting(self, config: dict) -> bool:
        """되묻는 중인가 = 멈춘 노드가 interrupt(질문)를 남겼나.

        "남은 노드가 있나(.next)"로 보면 안 된다 — Claude 오류·연결 끊김으로 노드가 중간에 실패해도 .next 가 남는다.
        그때 다음 메시지를 되묻기 답(resume)으로 넣으면 새 질문은 버려지고 실패한 앞 질문이 다시 실행된다.
        """
        return any(task.interrupts for task in self.graph.get_state(config).tasks)

    def send(self, thread_id: str, message: str) -> Reply:
        """사용자 메시지 하나 → 챗봇의 답."""
        *_, reply = self.stream(thread_id, message)  # 마지막 항목이 Reply
        return reply

    def stream(self, thread_id: str, message: str) -> Iterator[str | Reply]:
        """send 의 스트리밍판 — 답이 써지는 대로 글 조각(str)을 내보내고, 맨 끝에 완성된 Reply 를 하나 내보낸다.

        글 조각은 미리 보기용이다. 화면은 마지막 Reply.text(출처·면책 안내·[p.쪽] 표시까지 붙은 답)로 바꿔 보여 준다.
        되묻기·자살 신호 안내처럼 Claude 가 쓰지 않는 답은 글 조각 없이 Reply 만 나온다.
        """
        started = time.perf_counter()
        config = {"configurable": {"thread_id": thread_id}}
        if self.is_waiting(config):
            graph_input = Command(resume=message)
        else:
            # 새 질문. 이전 턴의 검색·판정 결과·되묻던 조건은 지워서 섞이지 않게 한다 (모은 가구 조건은 남김)
            # 앞 턴이 중간에 실패해 남은 노드가 있어도 여기서 처음(START)부터 새로 시작한다
            graph_input = {
                "messages": [{"role": "user", "content": message}],
                "eligibility": [], "passages": [], "sources": [], "pending_fields": [],
            }

        # custom = 노드가 get_stream_writer() 로 보낸 글 조각, values = 노드가 끝날 때마다의 전체 상태
        result, interrupts = {}, None
        for mode, data in self.graph.stream(graph_input, config, stream_mode=["custom", "values"]):
            if mode == "custom":
                yield data
            elif "__interrupt__" in data:  # 그래프가 질문을 남기고 멈춤 (invoke 결과의 __interrupt__ 와 같음)
                interrupts = data["__interrupt__"]
            else:
                result = data
        if interrupts:
            result = result | {"__interrupt__": interrupts}

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
        yield reply

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
