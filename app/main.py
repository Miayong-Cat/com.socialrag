"""FastAPI 진입점. (자바로 치면 @SpringBootApplication 클래스)

서버를 켤 때 가장 먼저 읽히는 파일이다. 하는 일:
1. 서버 시작 시 DB 테이블이 없으면 만든다 (lifespan).
2. API 묶음(라우터)을 앱에 등록한다.

실행:
    uvicorn app.main:app --reload
      - app.main → 이 파일(app/main.py)
      - :app     → 아래에서 만든 변수 app
      - --reload → 코드를 고치면 서버가 자동으로 다시 시작됨 (개발용)
확인:
    http://127.0.0.1:8000/docs   (Swagger 화면이 자동 생성됨 — 여기서 API를 직접 눌러볼 수 있음)

새 API 파일을 추가했다면:
    app/routes/ 에 파일을 만들고, 아래 include_router 줄을 하나 더 추가한다.
"""

from contextlib import asynccontextmanager  # "시작할 때 / 끝날 때" 실행할 코드를 묶는 도구

from fastapi import FastAPI

import app.models  # noqa: F401 — 쓰지 않아도 import 해야 모든 테이블이 Base 에 등록돼 create_all 대상이 됨
from app.database import Base, engine
from app.routes import eligibility, welfare  # 판정 API, 복지제도 CRUD API (app/routes/)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버의 생애 주기. yield 앞은 서버 시작 시 1번, yield 뒤는 서버 종료 시 1번 실행된다.

    지금은 시작할 때 테이블만 만든다.
    create_all 은 "없는 테이블만" 만들고, 이미 있는 테이블과 데이터는 건드리지 않는다.
    (테이블 구조를 바꾸는 마이그레이션 도구는 아직 쓰지 않는 단계)
    """
    Base.metadata.create_all(engine)
    yield


# app: 서버 그 자체. uvicorn 이 이 변수를 찾아 실행한다.
#   title → Swagger(/docs) 화면 제목
app = FastAPI(title="복지제도 판정 RAG 챗봇 API", lifespan=lifespan)

# 라우터 등록: 각 파일에 정의한 /api/... 경로들이 서버에 연결된다.
app.include_router(welfare.router)
app.include_router(eligibility.router)  # /api/eligibility (app/routes/eligibility.py)
