"""청킹 — 지침서 쪽별 본문을 검색하기 좋은 크기의 조각(청크)으로 자른다.

RAG 는 질문과 비슷한 "조각"을 찾아 LLM 에게 근거로 준다.
쪽 전체(최대 6천 자)를 한 덩어리로 두면 검색이 뭉툭해지고, 너무 잘게 자르면 문맥이 끊긴다.

자르는 방법 두 가지 (build_chunks 의 strategy):
    "size"       줄 단위로 모아 CHUNK_SIZE 자 안팎으로 자르고, 앞 조각의 끝 몇 줄을 다음 조각에 겹친다. (4단계)
    "structure"  지침서의 항목 구조(1 → 가. → 1) → 가) → (1))를 따라 자른다. (5단계, 기본값)
                 - 상위 항목(1, 가., 1))이 시작되면 거기서 새 조각을 시작한다
                   (가. 1) 은 앞 조각이 너무 짧으면 이어 붙임. 1단계는 항상 새로 시작).
                 - 조각마다 "지금 어느 항목 아래인지" 경로를 헤더로 붙인다.
                   예) [Ⅱ. 급여의 지급 > 3 급여의 중지 > 가. 중지 사유 [법 제30…] p.257
                   본문에는 "중지"라는 말이 없어도 헤더 덕분에 "급여 중지" 질문에 걸린다.
                 - 항목이 길면 CHUNK_SIZE 에서 자르고 끝 몇 줄을 겹친다 ("size" 와 같음).

이 파일이 하는 일 (DB·모델 없이 문자열만 다루는 순수 함수):
    1. clean_page        쪽마다 반복되는 머리말·쪽번호를 지우고, 머리말 속 장 이름(예: "Ⅲ. 소득조사")을 꺼낸다.
    2. split_lines       "size" 방식으로 한 쪽을 자른다.
    3. split_structured  "structure" 방식으로 한 쪽을 자른다 (항목 경로는 다음 쪽으로 이어짐).
    4. build_chunks      모든 쪽을 처리해 Chunk 목록을 만든다.

조각은 쪽을 넘지 않는다 → 답변에 "p.131" 처럼 정확한 쪽번호를 붙일 수 있다.

아직 하지 않는 것: 표 제외 (표에서 뽑힌 글자도 본문과 같이 들어감)
"""

import re
from dataclasses import dataclass

CHUNK_SIZE = 800      # 조각 하나의 목표 글자 수 (넘으면 다음 조각으로)
OVERLAP_LINES = 2     # 앞 조각 끝에서 다음 조각 앞으로 겹쳐 넣는 줄 수 (문장이 잘려도 문맥 유지)
MIN_CHUNK_CHARS = 50  # 이보다 짧은 조각은 버린다 (빈 쪽, 그림만 있는 쪽)
MIN_SPLIT_CHARS = 200 # "structure": 2~3단계 항목은 모은 글이 이만큼은 돼야 거기서 자른다 (짧은 조각 방지)
SPLIT_LEVEL = 3       # "structure": 이 단계까지의 항목(1, 가., 1))에서 새 조각을 시작한다
HEADING_CHARS = 30    # 헤더 경로에 넣을 항목 제목의 최대 글자 수

# 지침서 항목 번호 — 단계 순서대로. 예) "3 급여의 중지" → "가. 중지 사유" → "1) …" → "가) …" → "(1) …"
HEADINGS = [
    re.compile(r"^\d{1,2} [가-힣]"),   # 1단계: "3 급여의 중지"
    re.compile(r"^[가-하]\. "),         # 2단계: "가. 중지 사유"
    re.compile(r"^\d{1,2}\) "),         # 3단계: "1) 신청"
    re.compile(r"^[가-하]\) "),         # 4단계: "가) 생활준비금"
    re.compile(r"^\(\d{1,2}\) "),       # 5단계: "(1) 세대별 주민등록표에 …"
]

# 지침서의 구분별 PDF 쪽 범위 (2026 PDF 목차 기준 — 새 연도 PDF는 목차를 보고 고칠 것)
#   front    표지·목차·개정 대비표 — 요약표라 검색 결과에 끼어들기 쉬움
#   body     본문 (제1~8편) — 기본 검색 대상
#   form     서식 (제9편) — 신청서·동의서 양식
#   appendix 부록 (제10편) — 감면제도·법률구조 등 안내
PARTS = [(1, 28, "front"), (29, 420, "body"), (421, 498, "form"), (499, 10_000, "appendix")]

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
    part: str        # 구분: front / body / form / appendix (PARTS 참고)
    text: str        # 조각 본문
    heading: str = ""  # 항목 경로. 예: "3 급여의 중지 > 가. 중지 사유" ("structure" 방식만)

    def embedding_text(self) -> str:
        """임베딩·LLM 에 넘길 글 = 헤더 + 본문. 예: "[Ⅲ. 소득조사 > 4) 근로를 유인…] p.131\\n…" """
        path = " > ".join(x for x in (self.section, self.heading) if x)
        header = f"[{path}] p.{self.page}" if path else f"p.{self.page}"
        return f"{header}\n{self.text}"


def part_of(page: int) -> str:
    """쪽번호 → 구분 이름."""
    for first, last, name in PARTS:
        if first <= page <= last:
            return name
    raise ValueError(f"PARTS 에 없는 쪽번호: {page}")


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


def heading_level(line: str) -> int | None:
    """항목 번호로 시작하는 줄이면 단계(1~5), 아니면 None."""
    for level, pattern in enumerate(HEADINGS, start=1):
        if pattern.match(line):
            return level
    return None


def split_structured(lines: list[str], path: list[str]) -> list[tuple[str, str]]:
    """"structure" 방식으로 한 쪽을 자른다. 반환: [(조각 본문, 항목 경로), …]

    path: 쪽이 시작될 때의 항목 경로 (단계별 제목 목록). 이 함수가 직접 고쳐서
          다음 쪽으로 이어지게 한다 — 항목은 쪽을 넘어 계속되므로.
    """
    chunks: list[tuple[str, str]] = []
    current: list[str] = []
    size = 0
    carried = 0           # current 앞쪽에 겹침으로 넘어온 줄 수 (이미 앞 조각에 들어 있음)
    only_headings = True  # current 에 아직 항목 제목 줄만 있는지

    def path_text() -> str:
        return " > ".join(x for x in path if x)

    chunk_path = path_text()  # 지금 모으는 조각의 헤더

    def flush(keep: int) -> None:
        nonlocal current, size, carried, only_headings
        chunks.append(("\n".join(current), chunk_path))
        current = current[-keep:] if keep else []
        size = sum(len(x) + 1 for x in current)
        carried = len(current)
        only_headings = not current

    for line in lines:
        level = heading_level(line)
        if level is not None:
            # 상위 항목이 시작되면 새 조각. 1단계("3 급여의 중지")는 앞 조각이 짧아도 항상 자른다
            #   — 안 자르면 새 항목 내용에 앞 항목의 헤더가 붙는다.
            if (level == 1 and not only_headings) or (level <= SPLIT_LEVEL and size >= MIN_SPLIT_CHARS):
                flush(keep=0)
            del path[level - 1 :]                          # 같은 단계·하위 단계 제목은 버리고
            path.extend([""] * (level - 1 - len(path)))    # (중간 단계를 건너뛴 경우 빈칸)
            path.append(line[:HEADING_CHARS])              # 이 항목 제목을 경로에 넣음
            if only_headings:
                # 조각이 제목 줄로만 시작하는 동안은 가장 깊은 제목까지 헤더에 반영
                # 예) "3 급여의 중지" 다음 줄이 "가. 중지 사유" → 헤더 "3 급여의 중지 > 가. 중지 사유"
                chunk_path = path_text()
        elif current and size + len(line) > CHUNK_SIZE:
            flush(keep=OVERLAP_LINES)                      # 항목이 길면 글자 수로 자르고 끝 몇 줄을 겹침
            chunk_path = path_text()
        current.append(line)
        size += len(line) + 1
        if level is None:
            only_headings = False

    # 남은 줄이 겹침으로 넘어온 줄뿐이면 이미 앞 조각에 들어 있으므로 버린다.
    if len(current) > carried:
        chunks.append(("\n".join(current), chunk_path))
    return chunks


def build_chunks(pages: list[dict], strategy: str = "structure") -> list[Chunk]:
    """쪽 목록({"page": 쪽번호, "text": 본문} — text_2026.jsonl 한 줄)으로 청크 목록을 만든다.

    장 이름은 홀수 쪽 머리말에만 있으므로, 머리말이 없는 쪽은 바로 앞 쪽의 장 이름을 이어 쓴다.
    strategy: "structure"(항목 구조) 또는 "size"(글자 수) — 파일 맨 위 설명 참고.
    """
    chunks = []
    section = ""
    path: list[str] = []  # "structure" 의 항목 경로 (쪽을 넘어 이어짐)
    for page in pages:
        found, lines = clean_page(page["text"])
        if found:
            if found != section:
                path = []  # 장이 바뀌면 항목 경로도 새로 시작
            section = found
        if strategy == "structure":
            pieces = split_structured(lines, path)
        elif strategy == "size":
            pieces = [(text, "") for text in split_lines(lines)]
        else:
            raise ValueError(f"알 수 없는 청킹 방법: {strategy}")
        kept = [(text, heading) for text, heading in pieces if len(text) >= MIN_CHUNK_CHARS]
        for i, (text, heading) in enumerate(kept):
            chunks.append(
                Chunk(
                    page=page["page"],
                    index=i,
                    section=section,
                    part=part_of(page["page"]),
                    text=text,
                    heading=heading,
                )
            )
    return chunks
