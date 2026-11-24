"""답변 생성 — 검색한 청크를 근거로 LLM 이 질문에 답하고, 근거 쪽번호를 붙인다.

인용은 번호 표시 + 코드 검증으로 만든다:
    청크마다 [문단 1], [문단 2] 번호를 붙여 넘기고, LLM 에게 근거로 쓴 문장 끝에 [1] 처럼 적게 한다.
    코드는 그 표시를 그대로 믿지 않고 답변 문장과 해당 청크를 대조해서,
    겹치는 내용이 있을 때만 [p.쪽] 과 출처로 바꾼다. 없는 번호·근거가 안 맞는 표시는 지운다.
    → 쪽번호와 인용문은 LLM 의 말이 아니라 코드가 원문에서 가져온 값이다 (LLM 에게는 쪽번호를 주지 않는다).
    한계: 글자가 겹치는지만 보므로, 문단과 같은 낱말로 틀린 말을 하는 경우까지 잡지는 못한다.

판정(수급 가능 여부·금액 계산)은 여기서 하지 않는다. 그건 판정 엔진(app/eligibility/)의 일이고,
이 파일은 지침서 내용을 찾아 설명하는 일만 한다.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.config import ANSWER_MODEL, LLM_CONTEXT_TOKENS
from app.llm import make_client


class Passage(Protocol):
    """답변 근거로 넘기는 지침서 문단 — generator 는 이 네 칸만 읽는다.

    DB 모델(app/models 의 GuideChunk)에 묶지 않으려고 "이 칸들이 있으면 된다"로 정했다.
    GuideChunk(CLI)도, 챗봇 상태의 dict 를 바꾼 가벼운 객체(app/chat/graph.py)도 그대로 넘길 수 있다.
    """

    page: int           # 지침서 쪽번호
    section: str        # 장 이름
    heading: str | None  # 항목 경로 (없으면 None)
    text: str           # 본문

SYSTEM_PROMPT = """\
당신은 「국민기초생활보장 사업안내」 지침서를 근거로 복지 담당자와 시민의 질문에 답하는 도우미입니다.

- 함께 주어진 지침서 문단에 있는 내용만으로 답하세요. 문단에 없는 내용은 추측하지 말고 "제공된 지침서 문단에서는 찾을 수 없습니다"라고 말하세요.
- 문단의 내용을 쓴 문장 끝에는 근거 문단 번호를 [1] 또는 [1, 3] 처럼 적으세요. 예) 근로소득은 30%를 공제합니다. [2]
- 특정 가구의 수급 가능 여부나 금액은 직접 계산하지 마세요. 별도의 판정 엔진이 계산합니다. 기준과 절차를 설명하는 데 집중하세요.
- [판정 엔진 결과]가 함께 주어지면 그 결과가 정답입니다. 다시 계산하거나 바꾸지 말고, 사용자에게 이미 표로 보여 주었으니 숫자를 되풀이하기보다 왜 그런 결과인지(어떤 기준이 적용됐는지)와 다음에 할 일(신청 방법, 추가로 확인할 점)을 지침서 문단을 근거로 설명하세요.
- 한국어로, 쉬운 말로, 핵심부터 간결하게 답하세요.
"""

# 로컬 모델은 시스템 프롬프트의 지시를 긴 문단 뒤에서 잊기 쉬워, 질문 바로 뒤에서 한 번 더 말한다
CITATION_REMINDER = "(문단의 내용을 쓴 문장마다 끝에 근거 문단 번호를 [1] 처럼 적으세요. 문단에 없는 절차·서류·기관은 쓰지 마세요.)"
CITATION_MARK = re.compile(r"\s*\[(?:문단\s*)?(\d+(?:\s*,\s*(?:문단\s*)?\d+)*)\]")
MIN_OVERLAP = 0.2  # 답변 문장의 글자 쌍 중 이만큼은 문단에 있어야 그 문단을 근거로 인정한다


@dataclass
class Source:
    """답변의 근거 하나."""

    page: int           # 지침서 쪽번호
    section: str        # 장 이름
    quote: str          # 근거 문단에서 코드가 찾아 온 원문 문장


@dataclass
class Answer:
    """답변 = 본문 + 근거 목록."""

    text: str                                           # 답변 본문. 인용한 문장 뒤에 [p.131] 표시
    sources: list[Source] = field(default_factory=list)


def build_documents(chunks: Sequence[Passage]) -> str:
    """청크 목록 → LLM 에 넘길 번호 붙은 문단 글. 번호는 1부터, 쪽번호는 넣지 않는다 (코드가 붙인다)."""
    return "\n\n".join(
        # 제목 = 장 이름 > 항목 경로. LLM 이 문단의 위치(어느 제도·절차인지)를 알게 한다.
        f"[문단 {number}] {' > '.join(x for x in (chunk.section, chunk.heading) if x)}\n{chunk.text}"
        for number, chunk in enumerate(chunks, start=1)
    )


def _pairs(text: str) -> set[str]:
    """글 → 공백·기호를 뺀 연속 두 글자 집합 (한국어는 조사가 붙어 낱말 단위 비교가 잘 안 맞는다)."""
    letters = re.sub(r"[^\w%]", "", text)
    return {letters[i:i + 2] for i in range(len(letters) - 1)}


def _overlap(sentence: str, text: str) -> float:
    """sentence 의 글자 쌍 중 text 에 있는 비율 (0~1)."""
    pairs = _pairs(sentence)
    return len(pairs & _pairs(text)) / len(pairs) if pairs else 0.0


def find_quote(sentence: str, chunk_text: str) -> str:
    """청크에서 답변 문장과 가장 많이 겹치는 원문 한 문장."""
    candidates = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", chunk_text) if s.strip()]
    return max(candidates, key=lambda c: _overlap(sentence, c), default=chunk_text.strip())


def parse_answer(raw: str, chunks: Sequence[Passage]) -> Answer:
    """LLM 답 → Answer. 문단 번호 표시를 검증해 [p.쪽번호] 로 바꾸고, 근거 목록을 모은다."""
    parts, sources, start = [], [], 0
    for mark in CITATION_MARK.finditer(raw):
        before = raw[start:mark.start()]
        parts.append(before)
        start = mark.end()
        sentence = re.split(r"(?<=[.!?])\s+", before.strip())[-1]
        pages = []
        for number in (int(n) for n in re.findall(r"\d+", mark.group(1))):
            if not 1 <= number <= len(chunks):  # 없는 문단 번호
                continue
            chunk = chunks[number - 1]
            if _overlap(sentence, chunk.text) < MIN_OVERLAP:  # 문장이 그 문단 내용과 맞지 않음
                continue
            sources.append(Source(page=chunk.page, section=chunk.section, quote=find_quote(sentence, chunk.text)))
            if chunk.page not in pages:
                pages.append(chunk.page)
        if pages:
            parts.append(" [" + ", ".join(f"p.{p}" for p in pages) + "]")
    parts.append(raw[start:])
    return Answer(text="".join(parts).strip(), sources=sources)


def generate(
    question: str,
    chunks: Sequence[Passage],
    client=None,
    facts: str | None = None,
    on_text: Callable[[str], None] | None = None,
) -> Answer:
    """질문 + 근거 청크 → LLM 답변.

    facts: 판정 엔진 결과 등 "이미 확정된 사실" 글. 주어지면 질문 앞에 붙여 LLM 이 설명의 출발점으로 쓴다.
    on_text: 주어지면 스트리밍으로 받으며 글 조각마다 부른다 (화면에 답이 써지는 모습을 보여 주려고).
             조각에는 [1] 표시가 그대로 보이고, 돌려주는 Answer 는 스트리밍이든 아니든 같다.

    client 를 넘기지 않으면 새로 만든다 (테스트에서는 가짜 client 를 넘김).
    """
    client = client or make_client()
    # 문단을 먼저, 질문을 마지막에 둔다.
    content = "\n\n".join([
        build_documents(chunks),
        *([f"[판정 엔진 결과]\n{facts}"] if facts else []),
        f"[질문]\n{question}",
        CITATION_REMINDER,
    ])
    request = dict(
        model=ANSWER_MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
        options={"temperature": 0.2, "num_ctx": LLM_CONTEXT_TOKENS},
    )
    if on_text is None:
        return parse_answer(client.chat(**request).message.content, chunks)
    # 스트리밍: 글자가 생기는 대로 on_text 로 넘긴다. 인용·쪽번호는 다 받은 뒤에 붙인다
    pieces = []
    for part in client.chat(**request, stream=True):
        if part.message.content:
            pieces.append(part.message.content)
            on_text(part.message.content)
    return parse_answer("".join(pieces), chunks)
