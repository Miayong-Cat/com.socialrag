"""답변 생성 — 검색한 청크를 근거로 Claude 가 질문에 답하고, 근거 쪽번호를 붙인다.

Claude API 의 인용(citations) 기능을 쓴다:
    청크 하나 = 문서(document) 하나로 넘기고 citations 를 켜면,
    Claude 가 답의 각 문장이 어느 문서의 어느 문장에서 왔는지 돌려준다.
    → "이 답은 p.131 의 이 문장에 근거함"을 LLM 의 말이 아니라 API 결과로 확인할 수 있다 (환각 방지).

판정(수급 가능 여부·금액 계산)은 여기서 하지 않는다. 그건 판정 엔진(app/eligibility/)의 일이고,
이 파일은 지침서 내용을 찾아 설명하는 일만 한다.

API 키: .env 의 ANTHROPIC_API_KEY (anthropic 라이브러리가 환경변수에서 자동으로 읽음)
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import anthropic

from app.config import LLM_MODEL
from app.models import GuideChunk

SYSTEM_PROMPT = """\
당신은 「국민기초생활보장 사업안내」 지침서를 근거로 복지 담당자와 시민의 질문에 답하는 도우미입니다.

- 함께 주어진 지침서 문단에 있는 내용만으로 답하세요. 문단에 없는 내용은 추측하지 말고 "제공된 지침서 문단에서는 찾을 수 없습니다"라고 말하세요.
- 특정 가구의 수급 가능 여부나 금액은 직접 계산하지 마세요. 별도의 판정 엔진이 계산합니다. 기준과 절차를 설명하는 데 집중하세요.
- [판정 엔진 결과]가 함께 주어지면 그 결과가 정답입니다. 다시 계산하거나 바꾸지 말고, 사용자에게 이미 표로 보여 주었으니 숫자를 되풀이하기보다 왜 그런 결과인지(어떤 기준이 적용됐는지)와 다음에 할 일(신청 방법, 추가로 확인할 점)을 지침서 문단을 근거로 설명하세요.
- 한국어로, 쉬운 말로, 핵심부터 간결하게 답하세요.
"""


@dataclass
class Source:
    """답변의 근거 하나."""

    page: int           # 지침서 쪽번호
    section: str        # 장 이름
    quote: str          # Claude 가 인용한 원문 문장


@dataclass
class Answer:
    """답변 = 본문 + 근거 목록."""

    text: str                                           # 답변 본문. 인용한 문장 뒤에 [p.131] 표시
    sources: list[Source] = field(default_factory=list)


def build_documents(chunks: list[GuideChunk]) -> list[dict]:
    """청크 목록 → Claude 에 넘길 문서(document) 블록 목록. 순서가 곧 document_index."""
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": chunk.text},
            # 제목 = 장 이름 > 항목 경로 + 쪽. Claude 가 문단의 위치(어느 제도·절차인지)를 알게 한다.
            "title": " > ".join(x for x in (chunk.section, chunk.heading) if x) + f" p.{chunk.page}",
            "citations": {"enabled": True},
        }
        for chunk in chunks
    ]


def parse_response(response, chunks: list[GuideChunk]) -> Answer:
    """Claude 응답 → Answer. 인용이 달린 문장 뒤에 [p.쪽번호] 를 붙이고, 근거 목록을 모은다.

    citations 를 켜면 응답 본문이 여러 text 블록으로 나뉘어 오고,
    근거가 있는 블록에는 citations 목록이 붙는다 (document_index = 몇 번째 문서인지).
    """
    if response.stop_reason == "refusal":
        return Answer(text="이 질문에는 답변할 수 없습니다.")

    parts, sources = [], []
    for block in response.content:
        if block.type != "text":     # 생각(thinking) 블록 등은 건너뜀
            continue
        parts.append(block.text)
        pages = []
        for citation in getattr(block, "citations", None) or []:
            chunk = chunks[citation.document_index]
            sources.append(Source(page=chunk.page, section=chunk.section, quote=citation.cited_text.strip()))
            if chunk.page not in pages:
                pages.append(chunk.page)
        if pages:
            parts.append(" [" + ", ".join(f"p.{p}" for p in pages) + "]")
    return Answer(text="".join(parts).strip(), sources=sources)


def generate(
    question: str,
    chunks: list[GuideChunk],
    client: anthropic.Anthropic | None = None,
    facts: str | None = None,
    on_text: Callable[[str], None] | None = None,
) -> Answer:
    """질문 + 근거 청크 → Claude 답변.

    facts: 판정 엔진 결과 등 "이미 확정된 사실" 글. 주어지면 질문 앞에 붙여 Claude 가 설명의 출발점으로 쓴다.
    on_text: 주어지면 스트리밍으로 받으며 글 조각마다 부른다 (화면에 답이 써지는 모습을 보여 주려고).
             돌려주는 Answer 는 스트리밍이든 아니든 같다.

    client 를 넘기지 않으면 새로 만든다 (테스트에서는 가짜 client 를 넘김).
    fallbacks="default": Claude 의 안전 분류기가 요청을 거절하면 서버가 다른 모델로 자동 재시도한다.
    """
    client = client or anthropic.Anthropic()
    request = dict(
        model=LLM_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium"},  # 지침서 요약·설명 수준의 작업이라 medium
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                # 문서 블록을 먼저, 질문을 마지막에 둔다.
                "content": [
                    *build_documents(chunks),
                    *([{"type": "text", "text": f"[판정 엔진 결과]\n{facts}"}] if facts else []),
                    {"type": "text", "text": question},
                ],
            }
        ],
    )
    if on_text is None:
        response = client.beta.messages.create(**request)
    else:
        # 스트리밍: 글자가 생기는 대로 on_text 로 넘긴다. 인용·쪽번호는 다 받은 뒤 최종 응답으로 붙인다
        with client.beta.messages.stream(**request) as stream:
            for text in stream.text_stream:
                on_text(text)
            response = stream.get_final_message()
    return parse_response(response, chunks)
