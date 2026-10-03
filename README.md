# 복지제도 판정 RAG 챗봇

사용자 조건(나이·가구원 수·소득 등)으로 **복지제도 수급 가능 여부를 코드로 판정**하고,
그 근거를 지침서에서 찾아 설명하는 챗봇.

- 판정 = 결정론적 계산(코드) · 설명 = RAG + LLM
- 자세한 기획: `RAG_사회복지_챗봇개발가이드.md`

## 폴더 구조

```
app/                  API 서버 (FastAPI)
├── config.py         설정 한 곳 — 기준 연도, 파일 경로, DB 주소
├── main.py           진입점 — 서버 실행, 라우터 등록
├── database.py       DB 연결 (PostgreSQL, 접속 정보는 .env)
├── models/           DB 테이블 정의 — 테이블 하나 = 파일 하나
│   ├── welfare_program.py  welfare_programs 테이블
│   └── median_income.py    median_incomes 테이블
├── schemas.py        요청/응답 형식 + 입력 검증
├── routes/
│   └── welfare.py    복지제도 CRUD API
└── eligibility/      판정 엔진 (LLM 없이 지침서 산식 그대로, DB 접근 없는 순수 함수)
    ├── threshold.py  선정기준액 계산 (중위소득 × 비율, 8인 이상 확장)
    └── judge.py      소득인정액 ≦ 선정기준액 비교 → 제도별 충족 여부
ingestion/            PDF → 가공 데이터 → DB (서버와 따로 실행)
├── extract_criteria.py  [1] 선정기준표 → data/processed/criteria_2026.json
├── extract_text.py      [2] 전체 본문 → data/processed/text_2026.jsonl
└── load_criteria.py     [3] criteria JSON → DB
tests/                pytest 테스트 — 파일 이름 = test_<대상 파일 이름>
├── conftest.py       공통 준비물 (메모리 DB, API 클라이언트)
└── guide_2026.py     테스트 기대값으로 쓰는 2026 지침서 숫자
spike/                0단계 실험 기록 (결론: spike/README.md)
data/                 원본 PDF·가공 결과 (커밋 안 함, 공공누리 4유형)
docker-compose.yml    DB 서버 실행 설정 (PostgreSQL + pgvector)
.env.example          접속 정보 예시 → 복사해서 .env 로 (.env 는 커밋 안 함)
```

**어디를 고치면 되나?**

| 하고 싶은 일 | 고칠 곳 |
|---|---|
| 새 연도 지침서 적재 | `app/config.py`의 `YEAR` → 적재 스크립트 다시 실행 |
| 파일 경로 변경 | `app/config.py` |
| DB 비밀번호·포트 변경 | `.env` (DB를 지우고 다시 만들어야 반영: `docker compose down -v` → `up -d`) |
| 테이블 추가·컬럼 변경 | `app/models/`에 파일 추가 → `app/models/__init__.py`에 import 한 줄 (+ API로 노출하면 `app/schemas.py`) |
| 새 API 추가 | `app/routes/`에 파일 추가 → `app/main.py`에 `include_router` |
| 판정 규칙 변경 | `app/eligibility/` (계산은 `threshold.py`, 비교는 `judge.py`) |

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
uvicorn app.main:app --reload     # → http://127.0.0.1:8000/docs  (DB가 켜져 있어야 함)
pytest                            # 메모리 DB를 쓰므로 Docker 없이도 실행됨
```

## DB 테이블

DB는 Docker로 띄운 **PostgreSQL 17** (+ 4단계 RAG용 pgvector 확장 포함 이미지). 테이블은 서버 시작·적재 시 자동 생성된다.

| 테이블 | 내용 |
|---|---|
| `welfare_programs` | 복지제도 (이름, 중위소득 대비 비율, 출처 쪽, 기준 연도 …) |
| `median_incomes` | 연도·가구원 수별 기준 중위소득 (지침서 표의 1~7인) |

선정기준 금액은 저장하지 않고 판정 엔진(`app/eligibility/threshold.py`)이 계산한다.

- 1~7인: **기준 중위소득 × 비율** (원 단위 반올림)
- 8인 이상: 1인 늘 때마다 **(7인 기준 − 6인 기준)** 을 더함 (지침서 p.78)

## 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 스파이크 — 기준표 추출 가능성 확인 | ✅ 텍스트+정규식으로 추출 |
| 1 | FastAPI 복지제도 CRUD | ✅ |
| 2 | 데이터 수집·정형화 | 🔶 기초생활보장 4종 적재 완료, 대상 제도 추가 예정 |
| 3 | 판정 엔진 | 🔶 선정기준 판정 완료, 소득인정액 계산 예정 |
| 4 | 기본 RAG 파이프라인 | |
