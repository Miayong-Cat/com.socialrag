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


def test_build_chunks_carries_section_forward():
    """장 이름이 없는 짝수 쪽은 앞 쪽의 장 이름을 이어 쓰고, 너무 짧은 쪽은 버린다."""
    body = "가" * 60  # MIN_CHUNK_CHARS(50)보다 긴 본문
    pages = [
        {"page": 1, "text": ""},                                                    # 빈 쪽 → 버림
        {"page": 131, "text": f"MINISTRY OF HEALTH AND WELFARE Ⅲ. 소득조사\n{body}\n131"},
        {"page": 132, "text": f"2026년 국민기초생활보장 사업안내\n{body}\n132"},
    ]
    chunks = build_chunks(pages)

    assert [(c.page, c.section) for c in chunks] == [(131, "Ⅲ. 소득조사"), (132, "Ⅲ. 소득조사")]
    assert chunks[1].embedding_text() == f"[Ⅲ. 소득조사] p.132\n{body}"
