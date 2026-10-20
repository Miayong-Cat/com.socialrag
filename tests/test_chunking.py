"""청킹 테스트 (대상: app/rag/chunking.py).

실행:
    pytest tests/test_chunking.py
"""

from app.rag import chunking
from app.rag.chunking import build_chunks, clean_page, split_lines


def test_clean_odd_page_header():
    """홀수 쪽: 머리말에서 장 이름을 꺼내고, 머리말·쪽번호 줄은 지운다."""
    section, lines = clean_page("MINISTRY OF HEALTH AND WELFARE Ⅲ. 소득조사\n4) 근로를 유인하기 위한 요인\n131")
    assert section == "Ⅲ. 소득조사"
    assert lines == ["4) 근로를 유인하기 위한 요인"]


def test_clean_doubled_header():
    """굵은 글씨가 겹쳐 뽑힌 머리말(MMIINN…)도 머리말로 인식한다."""
    text = "MMIINNIISSTTRRYY OOFF HHEEAALLTTHH AANNDD WWEELLFFAARREE Ⅰ. 감면제도 안내\n본문"
    assert clean_page(text) == ("Ⅰ. 감면제도 안내", ["본문"])


def test_clean_even_page_header():
    """짝수 쪽: 문서 제목 머리말은 지우고, 장 이름은 없다(None)."""
    section, lines = clean_page("2026년 국민기초생활보장 사업안내\n○ 본문 첫 줄\n\n○ 둘째 줄\n14")
    assert section is None
    assert lines == ["○ 본문 첫 줄", "○ 둘째 줄"]  # 빈 줄도 빠짐


def test_split_with_overlap(monkeypatch):
    """CHUNK_SIZE 를 넘으면 새 조각을 시작하고, 앞 조각의 끝 2줄을 겹쳐 넣는다."""
    monkeypatch.setattr(chunking, "CHUNK_SIZE", 20)  # 테스트에서만 조각 크기를 작게
    lines = ["aaaaa", "bbbbb", "ccccc", "ddddd", "eeeee"]  # 줄바꿈 포함 한 줄 6자

    assert split_lines(lines) == [
        "aaaaa\nbbbbb\nccccc",
        "bbbbb\nccccc\nddddd",
        "ccccc\nddddd\neeeee",
    ]


def test_split_short_page_is_one_chunk():
    """짧은 쪽은 조각 하나."""
    assert split_lines(["한 줄", "두 줄"]) == ["한 줄\n두 줄"]


def test_build_chunks_carries_section_forward():  # "size" 방식
    """장 이름이 없는 짝수 쪽은 앞 쪽의 장 이름을 이어 쓰고, 너무 짧은 쪽은 버린다."""
    body = "가" * 60  # MIN_CHUNK_CHARS(50)보다 긴 본문
    pages = [
        {"page": 1, "text": ""},                                                    # 빈 쪽 → 버림
        {"page": 131, "text": f"MINISTRY OF HEALTH AND WELFARE Ⅲ. 소득조사\n{body}\n131"},
        {"page": 132, "text": f"2026년 국민기초생활보장 사업안내\n{body}\n132"},
    ]
    chunks = build_chunks(pages, strategy="size")

    assert [(c.page, c.section) for c in chunks] == [(131, "Ⅲ. 소득조사"), (132, "Ⅲ. 소득조사")]
    assert chunks[1].embedding_text() == f"[Ⅲ. 소득조사] p.132\n{body}"


def test_part_of():
    """쪽번호 → 구분 (2026 PDF 기준)."""
    assert [chunking.part_of(p) for p in (10, 131, 450, 520)] == ["front", "body", "form", "appendix"]


def test_heading_level():
    """항목 번호 다섯 단계를 알아보고, 항목이 아닌 줄은 None."""
    lines = ["3 급여의 중지", "가. 중지 사유", "1) 신청", "가) 생활준비금", "(1) 세대별", "○ 본문", "2026년 기준"]
    assert [chunking.heading_level(x) for x in lines] == [1, 2, 3, 4, 5, None, None]


def test_split_structured(monkeypatch):
    """상위 항목(가.)이 시작되면 새 조각, 조각마다 항목 경로가 붙고 경로는 다음 쪽으로 이어진다."""
    monkeypatch.setattr(chunking, "MIN_SPLIT_CHARS", 10)  # 테스트에서만 짧은 조각도 허용
    path: list[str] = []
    lines = ["3 급여의 중지", "가. 중지 사유", "○ 소득인정액이 기준을 넘을 때", "나. 중지 절차", "○ 서면으로 통지"]

    pieces = chunking.split_structured(lines, path)

    assert pieces == [
        ("3 급여의 중지\n가. 중지 사유\n○ 소득인정액이 기준을 넘을 때", "3 급여의 중지 > 가. 중지 사유"),
        ("나. 중지 절차\n○ 서면으로 통지", "3 급여의 중지 > 나. 중지 절차"),
    ]
    assert path == ["3 급여의 중지", "나. 중지 절차"]  # 다음 쪽은 이 경로에서 이어 시작

    # 다음 쪽: 항목 번호 없이 시작해도 앞 쪽의 경로를 헤더로 쓴다
    assert chunking.split_structured(["○ 이어지는 내용"], path) == [("○ 이어지는 내용", "3 급여의 중지 > 나. 중지 절차")]


def test_structure_header_in_embedding_text():
    """임베딩용 글의 헤더 = [장 이름 > 항목 경로] p.쪽."""
    chunk = chunking.Chunk(page=257, index=0, section="Ⅱ. 급여의 지급", part="body", text="본문", heading="3 급여의 중지")
    assert chunk.embedding_text() == "[Ⅱ. 급여의 지급 > 3 급여의 중지] p.257\n본문"
