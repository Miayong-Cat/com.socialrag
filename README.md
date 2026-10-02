# 복지제도 판정 RAG 챗봇

사용자 조건(나이·가구원 수·소득 등)으로 **복지제도 수급 가능 여부를 코드로 판정**하고,
그 근거를 지침서에서 찾아 설명하는 챗봇.

- 판정 = 결정론적 계산(코드) · 설명 = RAG + LLM
- 자세한 기획: `RAG_사회복지_챗봇개발가이드.md`

## 폴더 구조

```
app/                  API 서버 (FastAPI)
├── main.py           진입점 — 서버 실행, 라우터 등록
├── database.py       DB 연결 (SQLite, data/app.db)
├── models.py         DB 테이블 정의
├── schemas.py        요청/응답 형식 + 입력 검증
└── routes/
    └── welfare.py    복지제도 CRUD API
ingestion/            PDF → 가공 데이터 → DB (서버와 따로 실행)
├── extract_criteria.py  [1] 선정기준표 → data/processed/criteria_2026.json
├── extract_text.py      [2] 전체 본문 → data/processed/text_2026.jsonl
└── load_criteria.py     [3] criteria JSON → DB
tests/                pytest 테스트 (공통 준비물: conftest.py)
spike/                0단계 실험 기록 (결론: spike/README.md)
data/                 원본 PDF·가공 결과 (커밋 안 함, 공공누리 4유형)
```

## 실행

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**데이터 적재** — `data/raw/`에 사업안내 PDF를 넣고 순서대로 실행 (다시 실행해도 중복 없음)

```bash
python -m ingestion.extract_criteria
python -m ingestion.extract_text
python -m ingestion.load_criteria
```

**서버·테스트**

```bash
uvicorn app.main:app --reload     # → http://127.0.0.1:8000/docs
pytest
```

## DB 테이블

| 테이블 | 내용 |
|---|---|
| `welfare_programs` | 복지제도 (이름, 중위소득 대비 비율, 출처 쪽, 기준 연도 …) |
| `median_incomes` | 연도·가구원 수별 기준 중위소득 (1~8인) |

선정기준 금액은 저장하지 않는다 → **기준 중위소득 × 비율 (원 단위 반올림)** 으로 계산.

## 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 스파이크 — 기준표 추출 가능성 확인 | ✅ 텍스트+정규식으로 추출 |
| 1 | FastAPI 복지제도 CRUD | ✅ |
| 2 | 데이터 수집·정형화 | 🔶 기초생활보장 4종 적재 완료, 대상 제도 추가 예정 |
| 3 | 판정 엔진 | |
| 4 | 기본 RAG 파이프라인 | |
