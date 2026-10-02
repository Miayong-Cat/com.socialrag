"""DB 연결 설정. (자바로 치면 DataSource + EntityManager 설정)

- 지금은 SQLite 파일 하나(data/app.db)를 쓴다.
- 나중에 PostgreSQL로 바꿀 때는 DATABASE_URL 환경변수만 바꾸면 된다.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'app.db'}")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    """모든 테이블 클래스의 부모."""


def get_db():
    """요청 하나당 세션 하나를 열고, 끝나면 닫는다. (FastAPI Depends로 주입)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
