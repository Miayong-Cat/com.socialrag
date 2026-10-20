"""답변 생성 테스트 (대상: app/rag/generator.py).

실제 Claude API 를 부르지 않는다 (비용·API 키·네트워크 없이 돌아가야 하므로).
가짜 client 가 "Claude 가 이렇게 답했다"는 응답을 돌려주게 하고,
    1) 요청이 올바른 모양으로 만들어지는지
    2) 응답의 인용(citations)이 쪽번호로 잘 바뀌는지
를 확인한다.

실행:
    pytest tests/test_generator.py
"""

from types import SimpleNamespace as NS  # 속성만 가진 간단한 가짜 객체를 만드는 도구

from app.models import GuideChunk
from app.rag.generator import build_documents, generate

CHUNKS = [
    GuideChunk(
        page=131,
        section="Ⅲ. 소득조사",
        heading="4) 근로를 유인하기 위한 요인",
        text="생계･주거･교육급여 수급(권)자의 근로･사업소득은 30% 공제 적용",
    ),
    GuideChunk(page=14, section="Ⅰ. 개요", text="생계급여 선정기준은 기준 중위소득의 32% 이하"),
]


class FakeClient:
    """client.beta.messages.create(...) 를 흉내 낸다. 받은 요청은 self.request 에 남긴다."""

    def __init__(self, response):
        self.request = None
        self.beta = NS(messages=NS(create=self._create))
        self._response = response

    def _create(self, **kwargs):
        self.request = kwargs
        return self._response


def text_block(text, citations=None):
    return NS(type="text", text=text, citations=citations)


def citation(document_index, cited_text):
    return NS(type="char_location", document_index=document_index, cited_text=cited_text)


def test_build_documents():
    """청크 하나 = 문서 하나. 인용 기능이 켜져 있고, 제목에 장 이름·항목 경로·쪽번호가 들어간다."""
    docs = build_documents(CHUNKS)
    assert docs[0]["source"]["data"] == CHUNKS[0].text
    assert docs[0]["title"] == "Ⅲ. 소득조사 > 4) 근로를 유인하기 위한 요인 p.131"
    assert docs[1]["title"] == "Ⅰ. 개요 p.14"  # 항목 경로가 없으면 장 이름만
    assert all(d["citations"] == {"enabled": True} for d in docs)


def test_generate_with_citations():
    """인용이 달린 문장 뒤에 [p.쪽] 이 붙고, 근거 목록에 쪽번호·원문이 들어간다."""
    response = NS(
        stop_reason="end_turn",
        content=[
            NS(type="thinking", thinking=""),                      # 생각 블록은 무시돼야 함
            text_block("근로소득은 30%를 공제합니다.", [citation(0, "근로･사업소득은 30% 공제 적용")]),
            text_block(" 더 궁금한 점은 문의하세요."),                # 인용 없는 문장
        ],
    )
    client = FakeClient(response)

    answer = generate("근로소득 공제는?", CHUNKS, client=client)

    assert answer.text == "근로소득은 30%를 공제합니다. [p.131] 더 궁금한 점은 문의하세요."
    assert [(s.page, s.quote) for s in answer.sources] == [(131, "근로･사업소득은 30% 공제 적용")]

    # 요청 모양: 문서 2개 + 질문이 마지막, 안전 거절 시 자동 재시도(fallbacks) 켜짐
    content = client.request["messages"][0]["content"]
    assert [b["type"] for b in content] == ["document", "document", "text"]
    assert content[-1]["text"] == "근로소득 공제는?"
    assert client.request["fallbacks"] == "default"


def test_refusal():
    """안전 분류기가 거절하면(stop_reason == "refusal") 본문을 읽지 않고 안내 문구를 돌려준다."""
    answer = generate("…", CHUNKS, client=FakeClient(NS(stop_reason="refusal", content=[])))
    assert answer.text == "이 질문에는 답변할 수 없습니다."
    assert answer.sources == []
