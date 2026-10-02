"""테스트 공통 준비물. pytest가 자동으로 읽는다.

테스트마다 빈 메모리 DB를 새로 만들어 쓰므로 실제 data/app.db는 건드리지 않는다.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def db(session_factory):
    """DB 세션 하나. (적재 스크립트처럼 DB를 직접 다루는 테스트용)"""
    with session_factory() as session:
        yield session


@pytest.fixture
def client(session_factory):
    """API 호출용 클라이언트. 앱의 DB를 메모리 DB로 바꿔 끼운다."""

    def get_test_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    yield TestClient(app)
    app.dependency_overrides.clear()
