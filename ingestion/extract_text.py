"""[적재 2/3] 사업안내 PDF 전체 본문을 쪽별 텍스트로 저장. (4단계 RAG 청킹의 재료)

RAG = 질문과 관련된 지침서 문단을 찾아 LLM에게 근거로 주는 방식.
그러려면 먼저 PDF 글자를 쪽 단위로 뽑아 두어야 한다. 이 스크립트가 그 일을 한다.

사용법:
    python -m ingestion.extract_text
읽는 파일:
    data/raw/2026_국민기초생활보장_사업안내.pdf   (app/config.py 의 GUIDE_PDF_PATH)
결과:
    data/processed/text_2026.jsonl               (app/config.py 의 TEXT_JSONL_PATH)
    JSONL = 한 줄에 JSON 하나. 여기서는 한 줄 = 한 쪽 = {"page": 쪽번호, "text": 본문}
"""

import json
import sys

import pdfplumber  # PDF에서 글자를 뽑는 라이브러리

from app.config import GUIDE_PDF_PATH, ROOT, TEXT_JSONL_PATH

# 글자가 이보다 적은 쪽은 품질 확인 대상으로 따로 알려 준다.
# (빈 쪽, 그림·스캔 이미지만 있는 쪽은 글자가 거의 안 뽑힘 → 나중에 OCR이 필요할 수 있음)
MIN_CHARS = 50


def main():
    """PDF의 모든 쪽을 차례로 읽어 JSONL 파일에 한 줄씩 쓴다."""
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 터미널 한글 깨짐 방지
    TEXT_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)  # 저장 폴더가 없으면 생성

    short_pages = []  # 글자가 너무 적은 쪽번호 모음
    # PDF(읽기)와 결과 파일(쓰기, "w")을 동시에 연다. 블록이 끝나면 둘 다 자동으로 닫힌다.
    with pdfplumber.open(GUIDE_PDF_PATH) as pdf, TEXT_JSONL_PATH.open("w", encoding="utf-8") as out:
        for page_no, page in enumerate(pdf.pages, start=1):  # 쪽번호를 1부터 셈
            # 글자가 하나도 없는 쪽은 extract_text() 가 None 을 돌려주므로 빈 문자열로 바꿈
            text = page.extract_text() or ""
            out.write(json.dumps({"page": page_no, "text": text}, ensure_ascii=False) + "\n")
            if len(text.strip()) < MIN_CHARS:  # strip() → 앞뒤 공백·줄바꿈 제외하고 셈
                short_pages.append(page_no)
        total = len(pdf.pages)

    print(f"저장 완료: {TEXT_JSONL_PATH.relative_to(ROOT)}  ({total}쪽)")
    print(f"글자가 {MIN_CHARS}자 미만인 쪽 {len(short_pages)}개: {short_pages}")


# 이 파일을 직접 실행했을 때만 main() 을 부른다.
if __name__ == "__main__":
    main()
