"""[적재 1/3] 기준 중위소득·급여별 선정기준표를 PDF에서 뽑아 JSON으로 저장.

PDF의 표를 "선 기반 표 추출"로 읽으면 셀이 어긋나서(spike/README.md 참고),
페이지 전체를 글자로 뽑은 뒤 정규식으로 필요한 숫자만 골라낸다.

뽑은 숫자는 저장 전에 스스로 검증한다:
    "선정기준액 = 기준 중위소득 × 비율"이 표의 모든 칸에서 1원도 틀리지 않아야 저장.

사용법:
    python -m ingestion.extract_criteria
읽는 파일:
    data/raw/2026_국민기초생활보장_사업안내.pdf   (app/config.py 의 GUIDE_PDF_PATH)
결과:
    data/processed/criteria_2026.json            (app/config.py 의 CRITERIA_JSON_PATH)

결과 JSON 모양 (금액 단위: 원/월, 키 "1"~"7" = 가구원 수):
    {
      "year": 2026,
      "median_income": {"by_household": {"1": 2564238, …}, "increment_per_extra_person": 959198},
      "benefits": {
        "생계급여": {"percent_of_median": 32, "by_household": {"1": 820556, …},
                     "increment_per_extra_person": 306943},
        "의료급여": {"percent_of_median": 40, "by_household": {…}},
        …
      }
    }
"""

import json  # 결과를 JSON 파일로 저장
import re    # 정규식: PDF 글자에서 숫자 패턴을 찾는 데 사용
import sys

import pdfplumber  # PDF에서 글자를 뽑는 라이브러리

from app.config import CRITERIA_JSON_PATH, GUIDE_PDF_PATH, ROOT, YEAR
from app.eligibility.threshold import percent_of  # 검증할 때 판정 엔진과 똑같은 반올림을 쓰기 위해

PAGE_NO = 14  # 선정기준표가 있는 PDF 쪽번호(1부터 셈). 책에 인쇄된 쪽번호로는 xii
HOUSEHOLD_SIZES = 7  # 표에 나오는 가구 수: 1인 ~ 7인
BENEFITS = ("생계급여", "의료급여", "주거급여", "교육급여")  # 표에서 읽을 급여 4종

# 금액 정규식: 쉼표로 세 자리씩 끊긴 숫자. 예) "2,564,238"
#   \d{1,3}        → 맨 앞 1~3자리 숫자
#   (?:,\d{3})+    → ",숫자3개" 덩어리가 1번 이상 반복 ((?: ) 는 그룹으로 따로 저장하지 않는다는 뜻)
AMOUNT = r"\d{1,3}(?:,\d{3})+"


def to_int(text: str) -> int:
    """"2,564,238" 같은 금액 글자를 정수 2564238 로 바꾼다."""
    return int(text.replace(",", ""))


def read_amounts(line: str) -> dict[str, int]:
    """금액이 7개 나열된 한 줄을 가구원 수별 딕셔너리로 바꾼다.

    예) '820,556 1,343,773 …' → {'1': 820556, '2': 1343773, …, '7': …}

    키를 문자열("1")로 쓰는 이유: JSON 파일의 키는 항상 문자열이라 저장·읽기 후에도 모양이 같다.
    금액이 정확히 7개가 아니면 PDF 글자가 예상과 다르다는 뜻이므로 바로 에러를 낸다.
    """
    amounts = re.findall(AMOUNT, line)  # 줄 안의 금액을 전부 찾아 리스트로
    if len(amounts) != HOUSEHOLD_SIZES:
        raise ValueError(f"금액이 {HOUSEHOLD_SIZES}개가 아님: {line!r}")
    # enumerate(…, start=1) → (1, 첫 금액), (2, 둘째 금액) … 순서로 꺼냄
    return {str(size): to_int(a) for size, a in enumerate(amounts, start=1)}


def parse_median_income(text: str) -> dict:
    """페이지 글자에서 기준 중위소득(1~7인)과 8인 이상 1인당 증가액을 읽는다.

    PDF 글자 예:
        기준 중위소득 2,564,238 4,199,292 … 9,515,150
        …
        기준 중위소득：1인 증가시마다 959,198원 증가   ← "：" 는 PDF에 들어 있는 전각 콜론
    """
    # ^ … $ + re.MULTILINE → "기준 중위소득 "으로 시작하는 한 줄 전체를 찾음
    line = re.search(r"^기준 중위소득 .+$", text, re.MULTILINE).group()
    # ( ) 로 감싼 부분(금액)만 group(1) 로 꺼냄
    increment = re.search(rf"기준 중위소득：1인 증가시마다 ({AMOUNT})원", text).group(1)
    return {
        "by_household": read_amounts(line),
        "increment_per_extra_person": to_int(increment),  # 8인 이상에서 1인당 더하는 금액
    }


def parse_benefit(text: str, name: str) -> dict:
    """급여 한 종류(예: 생계급여)의 비율과 1~7인 선정기준액을 읽는다.

    PDF 글자는 아래처럼 3줄 구조다:
        생계급여수급자
        820,556 1,343,773 … 3,044,848
        (기준중위소득 32%)

    정규식 풀이:
        ^{name}수급자\\n          → 1줄째: "생계급여수급자"
        (.+)\\n                   → 2줄째: 금액 줄 전체 → group(1)
        \\(기준중위소득 (\\d+)%\\)  → 3줄째: 괄호 안 숫자(32) → group(2)
    """
    match = re.search(rf"^{name}수급자\n(.+)\n\(기준중위소득 (\d+)%\)", text, re.MULTILINE)
    return {
        "percent_of_median": int(match.group(2)),
        "by_household": read_amounts(match.group(1)),
    }


def parse_livelihood_increment(text: str) -> int:
    """8인 이상에서 1인당 늘어나는 선정기준액. 원문 주석은 생계급여 금액만 예시로 준다.

    PDF 글자 예: "급여별 선정기준：1인 증가시마다 306,943원 증가"
    """
    return to_int(re.search(rf"급여별 선정기준：1인 증가시마다 ({AMOUNT})원", text).group(1))


def check(criteria: dict) -> None:
    """원문 숫자끼리 서로 맞는지 확인한다. 하나라도 틀리면 에러를 내서 저장을 막는다.

    확인 1: 모든 급여·모든 가구원 수에서  표의 선정기준액 == 기준 중위소득 × 비율 (반올림)
    확인 2: 생계급여 8인 이상 증가액 == 중위소득 증가액 × 32%
    → 정규식이 숫자를 잘못 읽었거나 PDF가 바뀌었으면 여기서 걸린다.
    """
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
    """PDF 읽기 → 숫자 뽑기 → 검증 → JSON 저장."""
    # 윈도우 터미널에서 한글이 깨지지 않도록 출력 인코딩을 UTF-8로 맞춘다.
    sys.stdout.reconfigure(encoding="utf-8")

    # with 블록이 끝나면 PDF 파일이 자동으로 닫힌다.
    with pdfplumber.open(GUIDE_PDF_PATH) as pdf:
        # pages 는 0부터 세므로 PAGE_NO - 1
        text = pdf.pages[PAGE_NO - 1].extract_text()

    criteria = {
        "year": YEAR,
        "unit": "원/월",
        "source": f"{YEAR}년 국민기초생활보장 사업안내 p.{PAGE_NO}(xii)",
        "median_income": parse_median_income(text),
        "benefits": {name: parse_benefit(text, name) for name in BENEFITS},
    }
    criteria["benefits"]["생계급여"]["increment_per_extra_person"] = parse_livelihood_increment(text)

    check(criteria)  # 검증 실패 시 여기서 에러가 나고 파일은 저장되지 않음

    # data/processed 폴더가 없으면 만든다 (이미 있으면 그냥 넘어감).
    CRITERIA_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False → 한글을 \uXXXX 가 아닌 글자 그대로 저장 / indent=2 → 사람이 읽기 좋게 줄바꿈
    CRITERIA_JSON_PATH.write_text(json.dumps(criteria, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장 완료: {CRITERIA_JSON_PATH.relative_to(ROOT)}  (검증 통과)")


# 이 파일을 직접 실행했을 때만 main() 을 부른다. (다른 파일에서 import 할 때는 실행 안 됨)
if __name__ == "__main__":
    main()
