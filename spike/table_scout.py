"""0단계 스파이크: 사업안내 PDF에서 '선정기준' 표 추출 가능성 정찰.

스파이크 = 본 개발 전에 "이 방법이 되는지" 빠르게 시험해 보는 실험 코드.
결론(표 추출 대신 텍스트+정규식 사용)은 spike/README.md 에 정리돼 있다.
본 코드(app/, ingestion/)에서는 이 파일을 쓰지 않는다 — 기록용으로 남겨 둔다.

app/ 패키지 없이 단독으로 실행되도록 PDF 경로를 직접 적어 두었다.

사용법:
    python spike/table_scout.py                 # 키워드가 나오는 페이지 목록
    python spike/table_scout.py 35 36           # 지정 페이지(1부터 셈)의 표 덤프
"""

import sys
from pathlib import Path

import pdfplumber  # PDF에서 글자·표를 뽑는 라이브러리

# 이 파일 위치(spike/)에서 두 단계 위 = 프로젝트 최상위 → data/raw/…pdf
PDF_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "2026_국민기초생활보장_사업안내.pdf"
KEYWORDS = ("선정기준", "기준 중위소득")  # 이 단어가 나오는 페이지를 찾는다


def find_pages(pdf):
    """모든 페이지를 훑어 키워드가 나오는 페이지와, 그 페이지에서 감지된 표 개수를 출력한다."""
    for i, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""  # 글자가 없는 페이지는 None → 빈 문자열
        # {키워드: 등장 횟수} — 등장한 키워드만 담음
        hits = {kw: text.count(kw) for kw in KEYWORDS if kw in text}
        if hits:
            n_tables = len(page.find_tables())  # 선(테두리) 기준으로 표를 찾아 개수만 셈
            print(f"p.{i:>3}  tables={n_tables}  {hits}")  # :>3 → 쪽번호를 3칸 오른쪽 정렬


def dump_tables(pdf, page_numbers):
    """지정한 페이지들의 표를 행 단위로 출력한다. 셀 사이는 " | " 로 구분."""
    for no in page_numbers:
        page = pdf.pages[no - 1]  # pages 는 0부터 세므로 -1
        tables = page.extract_tables()  # 표 목록. 표 하나 = 행 리스트, 행 하나 = 셀 리스트
        print(f"\n===== p.{no}: {len(tables)} table(s) =====")
        for t_idx, table in enumerate(tables, start=1):
            print(f"--- table {t_idx} ({len(table)} rows x {len(table[0]) if table else 0} cols)")
            for row in table:
                # 빈 셀(None)은 ""로, 셀 안 줄바꿈은 공백으로 바꿔 한 줄로 출력
                print(" | ".join((c or "").replace("\n", " ") for c in row))


def main():
    """인자가 있으면 그 페이지들의 표를 덤프하고, 없으면 키워드 페이지 목록을 출력한다."""
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 터미널 한글 깨짐 방지
    with pdfplumber.open(PDF_PATH) as pdf:
        if len(sys.argv) > 1:  # sys.argv[0] 은 파일 이름, [1:] 부터가 사용자가 준 쪽번호
            dump_tables(pdf, [int(a) for a in sys.argv[1:]])
        else:
            find_pages(pdf)


if __name__ == "__main__":
    main()
