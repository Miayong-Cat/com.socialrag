"""[적재 2/3] 사업안내 PDF 전체 본문을 쪽별 텍스트로 저장. (4단계 RAG 청킹의 재료)

사용법:
    python -m ingestion.extract_text
결과:
    data/processed/text_2026.jsonl   한 줄 = {"page": 쪽번호, "text": 본문}
"""

import json
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "data" / "raw" / "2026_국민기초생활보장_사업안내.pdf"
OUT_PATH = ROOT / "data" / "processed" / "text_2026.jsonl"

MIN_CHARS = 50  # 이보다 짧은 쪽은 품질 확인 대상(빈 쪽·그림만 있는 쪽 등)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    short_pages = []
    with pdfplumber.open(PDF_PATH) as pdf, OUT_PATH.open("w", encoding="utf-8") as out:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            out.write(json.dumps({"page": page_no, "text": text}, ensure_ascii=False) + "\n")
            if len(text.strip()) < MIN_CHARS:
                short_pages.append(page_no)
        total = len(pdf.pages)

    print(f"저장 완료: {OUT_PATH.relative_to(ROOT)}  ({total}쪽)")
    print(f"글자가 {MIN_CHARS}자 미만인 쪽 {len(short_pages)}개: {short_pages}")


if __name__ == "__main__":
    main()
