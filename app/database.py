"""DB 연결 설정. (자바로 치면 DataSource + EntityManager 설정)

이 파일이 하는 일 3가지:
1. engine        — DB와 실제로 연결하는 통로를 만든다.
2. Base          — 모든 테이블 클래스(app/models/)가 상속받는 부모 클래스.
3. get_db()      — API 요청이 올 때마다 DB 세션을 하나 빌려주고, 끝나면 반납한다.

DB 주소는 app/config.py 의 DATABASE_URL 에서 가져온다 (Docker로 띄운 PostgreSQL, .env 참고).
DB 서버가 꺼져 있어도 import 는 된다 — 실제 접속은 처음 쿼리를 보낼 때 일어난다.
"""

from sqlalchemy import create_engine, text  # DB 연결 통로(engine)를 만드는 함수, SQL 문자열 실행용
from sqlalchemy.orm import DeclarativeBase, sessionmaker  # 테이블 부모 클래스, 세션 공장

from app.config import DATABASE_URL

# engine: DB 연결을 관리하는 객체. 프로그램 전체에서 하나만 만들어 같이 쓴다.
engine = create_engine(DATABASE_URL)

# SessionLocal: 호출할 때마다 새 DB 세션을 만들어 주는 "세션 공장".
#   세션 = DB와 대화하는 작업 단위. 조회·추가·수정을 모았다가 commit()으로 한 번에 반영한다.
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    """모든 테이블 클래스의 부모.

    이 클래스를 상속한 클래스(예: WelfareProgram)는 SQLAlchemy가 테이블로 인식하고,
    Base.metadata.create_all(engine) 을 호출하면 해당 테이블이 DB에 만들어진다.
    """


def create_tables() -> None:
    """없는 테이블을 만든다. (서버 시작·적재 스크립트에서 호출)

    guide_chunks 테이블의 벡터 칸은 pgvector 확장이 있어야 만들 수 있으므로 확장을 먼저 켠다.
    CREATE EXTENSION IF NOT EXISTS → 이미 켜져 있으면 아무 일도 안 함.
    """
    import app.models  # noqa: F401 — 모든 테이블 클래스를 Base 에 등록 (빠지면 create_all 이 못 만듦)

    with engine.begin() as conn:  # begin() → 블록이 끝나면 자동 commit
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for statement in SCHEMA_UPDATES:
            conn.execute(text(statement))


# 이미 만들어진 테이블에 나중에 추가한 칸·제약. create_all 은 "없는 테이블"만 만들고 기존 테이블은 바꾸지 않으므로 직접 넣는다.
# (마이그레이션 도구를 쓰기 전까지의 최소한의 방법 — IF NOT EXISTS 라 여러 번 실행해도 안전)
SCHEMA_UPDATES = [
    "ALTER TABLE ai_search_logs ADD COLUMN IF NOT EXISTS error TEXT",  # 실패한 턴 기록 (app/models/ai_search_log.py)
    # 같은 이름·연도 제도 중복 금지 (app/models/welfare_program.py 의 UniqueConstraint 와 같은 이름)
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_welfare_programs_name_year ON welfare_programs (name, updated_year)",
]


def get_db():
    """요청 하나당 세션 하나를 열고, 끝나면 닫는다. (FastAPI Depends로 주입)

    사용 예 (app/routes/welfare.py):
        def list_programs(db: Session = Depends(get_db)): ...

    yield 를 쓰는 이유:
        yield 앞 = 요청 처리 전에 실행 (세션 열기)
        yield 뒤 = 요청 처리 후에 실행 (세션 닫기)
        finally 안에 있으므로 요청 중 에러가 나도 세션은 반드시 닫힌다.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
