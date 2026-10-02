"""0단계 스파이크: 사업안내 PDF에서 '선정기준' 표 추출 가능성 정찰.

사용법:
    python spike/table_scout.py                 # 키워드가 나오는 페이지 목록
    python spike/table_scout.py 35 36           # 지정 페이지(1-based)의 표 덤프
"""

import sys
from pathlib import Path

import pdfplumber

PDF_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "2026_국민기초생활보장_사업안내.pdf"
KEYWORDS = ("선정기준", "기준 중위소득")


def find_pages(pdf):
    for i, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        hits = {kw: text.count(kw) for kw in KEYWORDS if kw in text}
        if hits:
            n_tables = len(page.find_tables())
            print(f"p.{i:>3}  tables={n_tables}  {hits}")


def dump_tables(pdf, page_numbers):
    for no in page_numbers:
        page = pdf.pages[no - 1]
        tables = page.extract_tables()
        print(f"\n===== p.{no}: {len(tables)} table(s) =====")
        for t_idx, table in enumerate(tables, start=1):
            print(f"--- table {t_idx} ({len(table)} rows x {len(table[0]) if table else 0} cols)")
            for row in table:
                print(" | ".join((c or "").replace("\n", " ") for c in row))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with pdfplumber.open(PDF_PATH) as pdf:
        if len(sys.argv) > 1:
            dump_tables(pdf, [int(a) for a in sys.argv[1:]])
        else:
            find_pages(pdf)


if __name__ == "__main__":
    main()
