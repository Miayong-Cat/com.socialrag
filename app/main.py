"""FastAPI 진입점. (자바로 치면 @SpringBootApplication 클래스)

실행:
    uvicorn app.main:app --reload
확인:
    http://127.0.0.1:8000/docs   (Swagger 자동 생성)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routes import welfare


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 1번 실행: 테이블이 없으면 만든다 (지금 단계에선 마이그레이션 도구 없이)."""
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="복지제도 판정 RAG 챗봇 API", lifespan=lifespan)
app.include_router(welfare.router)
