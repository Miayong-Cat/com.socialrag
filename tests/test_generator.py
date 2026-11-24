"""답변 생성 테스트 (대상: app/rag/generator.py).

실제 LLM 을 부르지 않는다 (Ollama·모델 없이 돌아가야 하므로).
가짜 client 가 "LLM 이 이렇게 답했다"는 응답을 돌려주게 하고,
    1) 요청이 올바른 모양으로 만들어지는지
    2) 답의 문단 번호 표시가 검증을 거쳐 쪽번호로 잘 바뀌는지
를 확인한다.

실행:
    pytest tests/test_generator.py
"""

from types import SimpleNamespace as NS  # 속성만 가진 간단한 가짜 객체를 만드는 도구

from app.models import GuideChunk
from app.rag.generator import CITATION_REMINDER, build_documents, find_quote, generate, parse_answer

CHUNKS = [
    GuideChunk(
        page=131,
        section="Ⅲ. 소득조사",
        heading="4) 근로를 유인하기 위한 요인",
        text="생계･주거･교육급여 수급(권)자의 근로･사업소득은 30% 공제 적용",
    ),
    GuideChunk(page=14, section="Ⅰ. 개요", text="생계급여 선정기준은 기준 중위소득의 32% 이하"),
]


def reply(text):
    return NS(message=NS(content=text))


class FakeClient:
    """client.chat(...) 을 흉내 낸다. 받은 요청은 self.request 에 남긴다. stream=True 면 조각들을 돌려준다."""

    def __init__(self, text, pieces=None):
        self.request = None
        self._text = text
        self._pieces = pieces

    def chat(self, **kwargs):
        self.request = kwargs
        return (reply(p) for p in self._pieces) if kwargs.get("stream") else reply(self._text)


def test_build_documents():
    """청크마다 번호가 붙고, 제목에 장 이름·항목 경로가 들어간다. 쪽번호는 LLM 에게 주지 않는다 (코드가 붙임)."""
    documents = build_documents(CHUNKS)
    assert documents.startswith("[문단 1] Ⅲ. 소득조사 > 4) 근로를 유인하기 위한 요인\n생계･주거･교육급여")
    assert "[문단 2] Ⅰ. 개요\n생계급여 선정기준은" in documents  # 항목 경로가 없으면 장 이름만
    assert "131" not in documents


def test_generate_with_citations():
    """번호 표시가 달린 문장 뒤에 [p.쪽] 이 붙고, 근거 목록에 쪽번호·원문이 들어간다."""
    client = FakeClient("근로소득은 30% 공제 적용됩니다. [1] 더 궁금한 점은 문의하세요.")

    answer = generate("근로소득 공제는?", CHUNKS, client=client)

    assert answer.text == "근로소득은 30% 공제 적용됩니다. [p.131] 더 궁금한 점은 문의하세요."
    assert [(s.page, s.quote) for s in answer.sources] == [(131, CHUNKS[0].text)]

    # 요청 모양: 시스템 프롬프트 + 문단들 뒤에 질문이 마지막
    system, user = client.request["messages"]
    assert system["role"] == "system" and "[1]" in system["content"]
    assert user["content"].startswith("[문단 1]") and user["content"].endswith(f"[질문]\n근로소득 공제는?\n\n{CITATION_REMINDER}")


def test_citation_is_checked_against_the_passage():
    """LLM 의 표시를 그대로 믿지 않는다: 없는 문단 번호·내용이 안 맞는 문단은 인용이 되지 않고 표시만 지워진다."""
    missing = parse_answer("근로소득은 30% 공제 적용됩니다. [9]", CHUNKS)
    assert missing.text == "근로소득은 30% 공제 적용됩니다." and missing.sources == []

    unrelated = parse_answer("장례를 치르면 장제급여를 신청할 수 있어요. [1]", CHUNKS)
    assert unrelated.text == "장례를 치르면 장제급여를 신청할 수 있어요." and unrelated.sources == []


def test_multiple_citation_forms():
    """[1, 2] 와 [문단 1] 모양도 알아듣고, 같은 쪽은 한 번만 적는다."""
    both = parse_answer("생계급여 선정기준은 중위소득 32%이고 근로소득은 30% 공제 적용됩니다. [1, 2]", CHUNKS)
    assert both.text.endswith("[p.131, p.14]") and [s.page for s in both.sources] == [131, 14]

    named = parse_answer("근로소득은 30% 공제 적용됩니다. [문단 1]", CHUNKS)
    assert named.text.endswith("[p.131]")


def test_quote_is_the_closest_original_sentence():
    """인용문은 LLM 의 말이 아니라 청크 원문에서 가장 많이 겹치는 문장."""
    text = "해산급여는 출산 시 지급한다.\n근로소득은 30% 공제한다."
    assert find_quote("근로소득 30% 공제", text) == "근로소득은 30% 공제한다."


def test_facts_are_given_before_question():
    """판정 엔진 결과(facts)를 주면 문단들 뒤, 질문 앞에 [판정 엔진 결과] 로 들어간다."""
    client = FakeClient("설명")
    generate("받을 수 있나요?", CHUNKS, client=client, facts="| 생계급여 | ✅ 충족 |")

    content = client.request["messages"][1]["content"]
    assert content.index("[문단 2]") < content.index("[판정 엔진 결과]\n| 생계급여 | ✅ 충족 |") < content.index("[질문]\n받을 수 있나요?")


def test_streaming_passes_pieces_and_returns_same_answer():
    """on_text 를 주면 stream 으로 받아 조각마다 부르고, 결과는 스트리밍이 아닐 때와 같은 Answer (인용 포함)."""
    client = FakeClient(None, pieces=["30% 공제 ", "", "적용됩니다. [1]"])
    pieces = []

    answer = generate("공제는?", CHUNKS, client=client, on_text=pieces.append)

    assert pieces == ["30% 공제 ", "적용됩니다. [1]"]  # 빈 조각은 넘기지 않음
    assert answer.text == "30% 공제 적용됩니다. [p.131]"
    assert client.request["stream"] is True


def test_chatbot_answer_path_passes_dict_passages(monkeypatch):
    """챗봇이 실제로 쓰는 경로(app/chat/graph.py 의 default_deps().answer): 상태의 dict 문단 → generator → 답.

    generator 는 DB 모델이 아니라 Passage 칸(page·section·heading·text)만 읽는다 — dict 를 바꾼 가벼운 객체로도 문서가 맞게 만들어지는지.
    """
    from app.chat.graph import default_deps

    client = FakeClient("30% 공제 적용됩니다. [1]")
    monkeypatch.setattr("app.rag.generator.make_client", lambda: client)  # 진짜 LLM 대신
    passages = [{"page": 131, "section": "Ⅲ. 소득조사", "heading": "4) 근로를 유인하기 위한 요인", "text": "근로･사업소득은 30% 공제 적용"}]

    answer = default_deps().answer("공제는?", passages, None)

    assert "[문단 1] Ⅲ. 소득조사 > 4) 근로를 유인하기 위한 요인\n근로･사업소득은 30% 공제 적용" in client.request["messages"][1]["content"]
    assert answer.text == "30% 공제 적용됩니다. [p.131]"
    assert [(s.page, s.section) for s in answer.sources] == [(131, "Ⅲ. 소득조사")]
