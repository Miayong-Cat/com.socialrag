"""청킹 — 지침서 쪽별 본문을 검색하기 좋은 크기의 조각(청크)으로 자른다.

RAG 는 질문과 비슷한 "조각"을 찾아 LLM 에게 근거로 준다.
쪽 전체(최대 6천 자)를 한 덩어리로 두면 검색이 뭉툭해지고, 너무 잘게 자르면 문맥이 끊긴다.
그래서 줄 단위로 모아 CHUNK_SIZE 자 안팎으로 자르고, 앞 조각의 끝 몇 줄을 다음 조각에 겹쳐 둔다.

이 파일이 하는 일 (DB·모델 없이 문자열만 다루는 순수 함수):
    1. clean_page   쪽마다 반복되는 머리말·쪽번호를 지우고, 머리말 속 장 이름(예: "Ⅲ. 소득조사")을 꺼낸다.
    2. split_lines  한 쪽의 줄들을 CHUNK_SIZE 자 안팎의 조각으로 자른다 (겹침 OVERLAP_LINES 줄).
    3. build_chunks 모든 쪽을 처리해 Chunk 목록을 만든다.

조각은 쪽을 넘지 않는다 → 답변에 "p.131" 처럼 정확한 쪽번호를 붙일 수 있다.
조각 앞에는 "[장 이름] p.쪽번호" 헤더를 붙여 임베딩한다 (헤더가 있으면 문맥이 살아 검색이 잘 됨).

아직 하지 않는 것 (5단계 검색 품질 개선에서):
    - 가. 1) 같은 항목 구조를 따라 자르기 (지금은 글자 수 기준)
    - 표 제외 (지금은 표에서 뽑힌 글자도 본문과 같이 들어감)
"""

import re
from dataclasses import dataclass

CHUNK_SIZE = 800      # 조각 하나의 목표 글자 수 (넘으면 다음 조각으로)
OVERLAP_LINES = 2     # 앞 조각 끝에서 다음 조각 앞으로 겹쳐 넣는 줄 수 (문장이 잘려도 문맥 유지)
MIN_CHUNK_CHARS = 50  # 이보다 짧은 조각은 버린다 (빈 쪽, 그림만 있는 쪽)

# 홀수 쪽 머리말: "MINISTRY OF HEALTH AND WELFARE Ⅲ. 소득조사"
#   굵은 글씨가 두 번 찍혀 "MMIINNIISSTTRRYY …" 처럼 글자가 겹쳐 뽑히는 쪽도 있다.
SECTION_HEADER = re.compile(
    r"^(?:MINISTRY OF HEALTH AND WELFARE|MMIINNIISSTTRRYY OOFF HHEEAALLTTHH AANNDD WWEELLFFAARREE)\s*(.*)$"
)
# 짝수 쪽 머리말: "2026년 국민기초생활보장 사업안내"
TITLE_HEADER = re.compile(r"^\d{4}년 국민기초생활보장 사업안내$")
# 맨 아래 쪽번호: "14", 목차의 "iii" 같은 로마 숫자
PAGE_NUMBER = re.compile(r"^(?:\d+|[ivxlc]+)$")


@dataclass
class Chunk:
    """검색 단위 조각 하나."""

    page: int        # PDF 쪽번호 (답변의 근거 표시용)
    index: int       # 그 쪽 안에서 몇 번째 조각인지 (0부터)
    section: str     # 장 이름. 예: "Ⅲ. 소득조사" (모르면 빈 문자열)
    text: str        # 조각 본문

    def embedding_text(self) -> str:
        """임베딩·LLM 에 넘길 글 = 헤더 + 본문. 예: "[Ⅲ. 소득조사] p.131\\n…" """
        header = f"[{self.section}] p.{self.page}" if self.section else f"p.{self.page}"
        return f"{header}\n{self.text}"


def clean_page(text: str) -> tuple[str | None, list[str]]:
    """쪽 하나의 본문에서 머리말·쪽번호를 지운다.

    반환: (머리말에서 찾은 장 이름 — 없으면 None, 남은 줄 목록)
    """
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]  # 빈 줄 제거
    section = None

    if lines:
        match = SECTION_HEADER.match(lines[0])
        if match:
            section = match.group(1).strip() or None
            lines = lines[1:]
        elif TITLE_HEADER.match(lines[0]):
            lines = lines[1:]
    if lines and PAGE_NUMBER.match(lines[-1]):
        lines = lines[:-1]
    return section, lines


def split_lines(lines: list[str]) -> list[str]:
    """줄들을 CHUNK_SIZE 자 안팎의 조각으로 자른다. 조각 사이에 OVERLAP_LINES 줄이 겹친다.

    예) CHUNK_SIZE 를 넘는 순간 지금까지 모은 줄을 한 조각으로 내보내고,
        마지막 2줄을 들고 다음 조각을 시작한다.
    줄 하나가 CHUNK_SIZE 보다 길어도 자르지 않는다 (지침서에는 그런 줄이 거의 없음).
    """
    chunks = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) > CHUNK_SIZE:
            chunks.append("\n".join(current))
            current = current[-OVERLAP_LINES:]          # 끝 몇 줄을 다음 조각으로 넘김
            size = sum(len(x) + 1 for x in current)
        current.append(line)
        size += len(line) + 1                           # +1 = 줄바꿈 글자
    # 남은 줄이 겹침 줄뿐이면 이미 앞 조각에 들어 있으므로 버린다.
    if current and (not chunks or len(current) > OVERLAP_LINES):
        chunks.append("\n".join(current))
    return chunks


def build_chunks(pages: list[dict]) -> list[Chunk]:
    """쪽 목록({"page": 쪽번호, "text": 본문} — text_2026.jsonl 한 줄)으로 청크 목록을 만든다.

    장 이름은 홀수 쪽 머리말에만 있으므로, 머리말이 없는 쪽은 바로 앞 쪽의 장 이름을 이어 쓴다.
    """
    chunks = []
    section = ""
    for page in pages:
        found, lines = clean_page(page["text"])
        if found:
            section = found
        for i, text in enumerate(t for t in split_lines(lines) if len(t) >= MIN_CHUNK_CHARS):
            chunks.append(Chunk(page=page["page"], index=i, section=section, text=text))
    return chunks
