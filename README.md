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
│   ├── median_income.py    median_incomes 테이블
│   └── guide_chunk.py      guide_chunks 테이블 (지침서 청크 + 임베딩)
├── schemas.py        요청/응답 형식 + 입력 검증
├── routes/
│   ├── welfare.py    복지제도 CRUD API
│   └── eligibility.py  판정 API — 가구 정보 → 제도별 충족 여부 + 계산 내역
├── rag/              RAG — 지침서 근거 검색 + Claude 설명 (파일별 역할은 app/rag/__init__.py)
│   ├── chunking.py   쪽별 본문 → 청크 (머리말·쪽번호 제거, 장 이름 헤더)
│   ├── embedding.py  글 → 벡터 (BGE-m3, 로컬)
│   ├── retriever.py  질문과 가까운 청크 검색 (pgvector)
│   ├── generator.py  청크를 근거로 Claude 답변 + 인용 쪽번호
│   └── ask.py        터미널 질문 CLI
└── eligibility/      판정 엔진 (LLM 없이 지침서 산식 그대로, DB 접근 없는 순수 함수)
    ├── household.py  입력 형식 — 판정할 가구 (가구원 수, 지역, 소득, 재산)
    ├── standards.py  2026 지침서 숫자 (기본재산액, 주거용재산 한도, 환산율, 근로소득공제)
    ├── income.py     소득평가액 = 실제소득 − 가구특성별 지출비용 − 근로소득공제
    ├── asset.py      재산의 소득환산액 = (재산 − 기본재산액 − 부채) × 환산율
    ├── threshold.py  선정기준액 계산 (중위소득 × 비율, 8인 이상 확장)
    └── judge.py      소득인정액 ≦ 선정기준액 비교 → 제도별 충족 여부
ingestion/            PDF → 가공 데이터 → DB (서버와 따로 실행)
├── extract_criteria.py  [1] 선정기준표 → data/processed/criteria_2026.json
├── extract_text.py      [2] 전체 본문 → data/processed/text_2026.jsonl
├── load_criteria.py     [3] criteria JSON → DB
└── load_chunks.py       [4] 본문 → 청크 → 임베딩 → DB
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
| 새 연도 공제액·환산율 반영 | `app/eligibility/standards.py` (숫자마다 지침서 쪽번호 표시) |
| 판정 규칙 변경 | `app/eligibility/` (파일별 역할은 `app/eligibility/__init__.py` 참고) |

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
python -m ingestion.load_chunks     # 처음엔 BGE-m3 모델 다운로드(약 2.3GB) + CPU 임베딩으로 수 분 이상
```

**서버·테스트**

```bash
uvicorn app.main:app --reload     # → http://127.0.0.1:8000/docs  (DB가 켜져 있어야 함)
pytest                            # 메모리 DB를 쓰므로 Docker 없이도 실행됨
```

## 판정 API

`POST /api/eligibility` — 가구 정보를 보내면 DB에 적재된 그 연도의 모든 제도에 대해 판정한다.

```json
{"size": 1, "region": "서울", "earners": [{"monthly_income": 1100000}]}
```

응답의 `results`에 제도마다 소득평가액·재산의 소득환산액·소득인정액·선정기준액·충족 여부·근거 쪽번호가 담긴다.
입력 칸 설명은 `/docs` 화면 또는 `app/schemas.py`의 `EligibilityRequest` 참고.

## RAG 질문 (CLI)

```bash
python -m app.rag.ask "생계급여 근로소득 공제는 어떻게 되나요?"
python -m app.rag.ask "…" --search-only    # Claude 없이 검색 결과만 (API 키 불필요)
```

질문을 임베딩해 pgvector로 가까운 청크 5개를 찾고, Claude(`claude-opus-5-5`)가 그 청크만 근거로 답한다.
Claude API의 인용(citations) 기능으로 답변 문장마다 근거 쪽번호와 원문을 붙인다. API 키는 `.env`의 `ANTHROPIC_API_KEY`.

## DB 테이블

DB는 Docker로 띄운 **PostgreSQL 17** (+ 4단계 RAG용 pgvector 확장 포함 이미지). 테이블은 서버 시작·적재 시 자동 생성된다.

| 테이블 | 내용 |
|---|---|
| `welfare_programs` | 복지제도 (이름, 중위소득 대비 비율, 출처 쪽, 기준 연도 …) |
| `median_incomes` | 연도·가구원 수별 기준 중위소득 (지침서 표의 1~7인) |
| `guide_chunks` | 지침서 본문 청크 + BGE-m3 임베딩(1024차원, pgvector) |

선정기준 금액은 저장하지 않고 판정 엔진(`app/eligibility/threshold.py`)이 계산한다.

- 1~7인: **기준 중위소득 × 비율** (원 단위 반올림)
- 8인 이상: 1인 늘 때마다 **(7인 기준 − 6인 기준)** 을 더함 (지침서 p.78)

## 판정 계산 범위

소득인정액 = **소득평가액** + **재산의 소득환산액** (지침서 p.77)

| 자동 계산 | 직접 입력 (세부 규칙이 많아 아직 계산하지 않음) |
|---|---|
| 근로소득공제 (유형별, 의료급여는 일반 30% 공제 없음) | 가구특성별 지출비용 |
| 주거용재산 한도 초과분 → 일반재산 | 임차보증금 95% 평가, 자동차 유형 구분 |
| 생활준비금 500만원, 기본재산액·부채 순서대로 공제 | 공제 대상 부채 확인 |
| 재산 종류별 환산율 | 장기금융저축공제, 재산범위 특례 (미지원) |

## 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 스파이크 — 기준표 추출 가능성 확인 | ✅ 텍스트+정규식으로 추출 |
| 1 | FastAPI 복지제도 CRUD | ✅ |
| 2 | 데이터 수집·정형화 | 🔶 기초생활보장 4종 적재 완료, 대상 제도 추가 예정 |
| 3 | 판정 엔진 | ✅ 선정기준·소득인정액 계산 + 판정 API (`POST /api/eligibility`) |
| 4 | 기본 RAG 파이프라인 | ✅ 글자 수 청킹 + BGE-m3 + pgvector + Claude 인용 답변 (CLI) |
