"""테스트 공통 준비물(fixture). pytest가 자동으로 읽는다 — import 하지 않아도 된다.

fixture = 테스트 함수의 인자 이름으로 받아 쓰는 준비물.
    def test_xxx(db): …      → 아래 db() 가 만든 세션을 받음
    def test_xxx(client): …  → 아래 client() 가 만든 API 클라이언트를 받음

테스트마다 빈 메모리 DB(SQLite)를 새로 만들어 쓰므로 실제 DB(PostgreSQL)는 건드리지 않는다.
→ Docker를 켜지 않아도 pytest 가 돌아가고, 빠르다.
  (주의: 실제 DB와 종류가 달라서, PostgreSQL에만 있는 기능을 쓰게 되면 그 부분은 따로 확인해야 한다)
테스트끼리 데이터가 섞이지도 않는다 (테스트 하나 = 새 DB 하나).
"""

import pytest
from fastapi.testclient import TestClient  # 서버를 띄우지 않고 API를 호출해 보는 도구
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def session_factory():
    """빈 메모리 DB에 테이블을 만들고, 그 DB용 세션 공장을 돌려준다. (db·client 가 공통으로 사용)

    create_engine 인자 설명:
        "sqlite://"                       → 파일 없이 메모리에만 있는 DB
        check_same_thread=False           → TestClient 가 다른 스레드에서 DB를 써도 허용
        poolclass=StaticPool              → 연결을 하나만 계속 재사용
                                            (메모리 DB는 연결마다 새 DB가 되므로, 하나로 고정해야
                                             만든 테이블·데이터가 유지됨)
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)  # app/models/ 의 모든 테이블 생성 (app.main 을 import 할 때 등록됨)
    return sessionmaker(bind=engine)


@pytest.fixture
def db(session_factory):
    """DB 세션 하나. (적재 스크립트처럼 DB를 직접 다루는 테스트용)

    yield 앞 = 테스트 전 준비, yield 뒤(with 블록 종료) = 테스트 후 세션 닫기.
    """
    with session_factory() as session:
        yield session


@pytest.fixture
def client(session_factory):
    """API 호출용 클라이언트. 앱의 DB를 메모리 DB로 바꿔 끼운다."""

    def get_test_db():
        """원래 get_db 대신 쓸 함수: 실제 DB 대신 메모리 DB 세션을 준다."""
        with session_factory() as session:
            yield session

    # dependency_overrides → "get_db 를 요청하면 get_test_db 를 대신 줘라"
    app.dependency_overrides[get_db] = get_test_db
    yield TestClient(app)
    app.dependency_overrides.clear()  # 테스트가 끝나면 원래대로 되돌림
