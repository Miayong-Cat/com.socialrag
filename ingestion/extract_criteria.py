"""[적재 1/3] 기준 중위소득·급여별 선정기준표를 PDF에서 뽑아 JSON으로 저장.

선 기반 표 추출은 셀이 어긋나서(spike/README.md), 페이지 텍스트를 정규식으로 읽는다.

사용법:
    python -m ingestion.extract_criteria
결과:
    data/processed/criteria_2026.json
"""

import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "data" / "raw" / "2026_국민기초생활보장_사업안내.pdf"
OUT_PATH = ROOT / "data" / "processed" / "criteria_2026.json"

YEAR = 2026
PAGE_NO = 14  # PDF 쪽번호(1부터). 인쇄 쪽번호로는 xii
HOUSEHOLD_SIZES = 7  # 표에 나오는 가구 수: 1인 ~ 7인
BENEFITS = ("생계급여", "의료급여", "주거급여", "교육급여")

AMOUNT = r"\d{1,3}(?:,\d{3})+"  # 예: 2,564,238


def to_int(text: str) -> int:
    return int(text.replace(",", ""))


def read_amounts(line: str) -> dict[str, int]:
    """'820,556 1,343,773 ...' 한 줄 → {'1': 820556, '2': 1343773, ...}"""
    amounts = re.findall(AMOUNT, line)
    if len(amounts) != HOUSEHOLD_SIZES:
        raise ValueError(f"금액이 {HOUSEHOLD_SIZES}개가 아님: {line!r}")
    return {str(size): to_int(a) for size, a in enumerate(amounts, start=1)}


def parse_median_income(text: str) -> dict:
    line = re.search(r"^기준 중위소득 .+$", text, re.MULTILINE).group()
    increment = re.search(rf"기준 중위소득：1인 증가시마다 ({AMOUNT})원", text).group(1)
    return {
        "by_household": read_amounts(line),
        "increment_per_extra_person": to_int(increment),  # 8인 이상
    }


def parse_benefit(text: str, name: str) -> dict:
    """급여 한 종류. PDF 텍스트는 '생계급여수급자 / 금액줄 / (기준중위소득 32%)' 3줄 구조."""
    match = re.search(rf"^{name}수급자\n(.+)\n\(기준중위소득 (\d+)%\)", text, re.MULTILINE)
    return {
        "percent_of_median": int(match.group(2)),
        "by_household": read_amounts(match.group(1)),
    }


def parse_livelihood_increment(text: str) -> int:
    """8인 이상 증가액. 원문 주석은 생계급여 금액만 예시로 준다."""
    return to_int(re.search(rf"급여별 선정기준：1인 증가시마다 ({AMOUNT})원", text).group(1))


def percent_of(amount: int, percent: int) -> int:
    """amount × percent% 를 원 단위로 반올림. 원문 표가 이 방식으로 계산돼 있음."""
    return (amount * percent + 50) // 100


def check(criteria: dict) -> None:
    """원문 숫자끼리 서로 맞는지 확인: 선정기준 = 기준 중위소득 × 비율 (원 단위 반올림)."""
    median = criteria["median_income"]["by_household"]
    for name, benefit in criteria["benefits"].items():
        rate = benefit["percent_of_median"]
        for size, amount in benefit["by_household"].items():
            expected = percent_of(median[size], rate)
            if amount != expected:
                raise ValueError(f"{name} {size}인: 표 {amount} ≠ 계산 {expected}")

    median_increment = criteria["median_income"]["increment_per_extra_person"]
    livelihood = criteria["benefits"]["생계급여"]
    if livelihood["increment_per_extra_person"] != percent_of(median_increment, 32):
        raise ValueError("생계급여 8인 이상 증가액이 계산과 다름")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with pdfplumber.open(PDF_PATH) as pdf:
        text = pdf.pages[PAGE_NO - 1].extract_text()

    criteria = {
        "year": YEAR,
        "unit": "원/월",
        "source": f"{YEAR}년 국민기초생활보장 사업안내 p.{PAGE_NO}(xii)",
        "median_income": parse_median_income(text),
        "benefits": {name: parse_benefit(text, name) for name in BENEFITS},
    }
    criteria["benefits"]["생계급여"]["increment_per_extra_person"] = parse_livelihood_increment(text)

    check(criteria)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(criteria, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장 완료: {OUT_PATH.relative_to(ROOT)}  (검증 통과)")


if __name__ == "__main__":
    main()
