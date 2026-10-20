"""프로젝트 전체 설정 — 파일 경로와 DB 주소를 이 파일 한 곳에만 적는다.

왜 따로 두나?
- 경로가 여러 파일에 흩어져 있으면, PDF 이름이나 연도가 바뀔 때 전부 찾아 고쳐야 한다.
- 여기만 고치면 서버(app/)와 적재 스크립트(ingestion/)가 모두 같은 값을 쓴다.

다른 파일에서 쓰는 법:
    from app.config import GUIDE_PDF_PATH
"""

import os  # 환경변수(DB 접속 정보)를 읽기 위해 사용
from pathlib import Path  # 운영체제와 상관없이 경로를 "/"로 이어 붙이기 위해 사용
from urllib.parse import quote_plus  # 비밀번호 속 특수문자를 주소에 넣을 수 있게 바꿔 주는 함수

from dotenv import load_dotenv  # .env 파일을 읽어 환경변수로 올려 주는 함수 (python-dotenv)

# ── 기준 연도 ─────────────────────────────────────────────
# 지침서는 매년 새로 나온다. 새 연도 PDF를 적재할 때 이 숫자만 바꾸면
# 아래 파일 이름(…_2026.pdf, criteria_2026.json 등)이 같이 바뀐다.
YEAR = 2026

# ── 폴더 경로 ─────────────────────────────────────────────
# __file__ = 이 파일(app/config.py)의 위치
# .resolve()   → 절대 경로로 바꿈
# .parents[1]  → 두 단계 위 폴더 = 프로젝트 최상위(C:\M_Project01)
ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data"            # 데이터 전체 (git에 올리지 않음, .gitignore 참고)
RAW_DIR = DATA_DIR / "raw"          # 원본 PDF를 사람이 직접 넣어 두는 곳
PROCESSED_DIR = DATA_DIR / "processed"  # 적재 스크립트가 PDF에서 뽑아낸 결과를 저장하는 곳

# ── 파일 경로 ─────────────────────────────────────────────
# 원본: 보건복지부 「국민기초생활보장 사업안내」 PDF
GUIDE_PDF_PATH = RAW_DIR / f"{YEAR}_국민기초생활보장_사업안내.pdf"

# ingestion/extract_criteria.py 가 만들고, ingestion/load_criteria.py 가 읽는 파일
# (기준 중위소득 + 급여별 선정기준표)
CRITERIA_JSON_PATH = PROCESSED_DIR / f"criteria_{YEAR}.json"

# ingestion/extract_text.py 가 만드는 파일 (PDF 전체 본문, 4단계 RAG의 재료)
TEXT_JSONL_PATH = PROCESSED_DIR / f"text_{YEAR}.jsonl"

# ── RAG (4단계) ───────────────────────────────────────────
# 임베딩 모델: 글 → 벡터. 로컬에서 돌아가는 무료 한국어 지원 모델 (처음 실행 때 약 2.3GB 내려받음)
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024  # BGE-m3 벡터 길이 — guide_chunks 테이블의 벡터 칸 크기
# 답변 생성 LLM (Anthropic Claude). API 키는 .env 의 ANTHROPIC_API_KEY
LLM_MODEL = "claude-opus-5-5"

# ── DB 주소 ───────────────────────────────────────────────
# DB는 Docker로 띄운 PostgreSQL 서버다 (docker-compose.yml).
# 접속 정보(비밀번호 등)는 코드에 적지 않고 프로젝트 최상위의 .env 파일에서 읽는다.
#
# load_dotenv: .env 파일의 "이름=값" 줄들을 환경변수로 올려 준다.
#   이미 같은 이름의 환경변수가 있으면 덮어쓰지 않는다 (배포 서버에서 직접 설정한 값이 우선).
#   .env 가 없어도 에러는 나지 않는다 → 아래 os.getenv 에서 기본값이 쓰인다.
load_dotenv(ROOT / ".env")


def _postgres_url() -> str:
    """.env 의 POSTGRES_* 값들로 SQLAlchemy 접속 주소를 만든다.

    주소 모양: postgresql+pg8000://사용자:비밀번호@서버:포트/DB이름
        postgresql → DB 종류
        +pg8000    → 파이썬에서 PostgreSQL에 접속할 때 쓰는 라이브러리
                     (순수 파이썬이라 DLL이 없음. psycopg 는 윈도우 앱 제어 정책에 DLL이 차단돼서 쓰지 않음)
    """
    user = os.getenv("POSTGRES_USER", "welfare")
    # quote_plus: 비밀번호에 @ : / 같은 기호가 있어도 주소가 깨지지 않게 변환
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", ""))
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "welfare")
    return f"postgresql+pg8000://{user}:{password}@{host}:{port}/{db_name}"


# DATABASE_URL 환경변수를 직접 주면 그 주소를 그대로 쓰고 (예: 클라우드 DB),
# 없으면 .env 의 POSTGRES_* 값으로 만든다 (평소 로컬 개발).
DATABASE_URL = os.getenv("DATABASE_URL") or _postgres_url()
