"""복지제도 CRUD API. (자바로 치면 @RestController)

| 메서드 | 경로                     | 하는 일   | 성공 코드 |
|--------|--------------------------|-----------|-----------|
| POST   | /api/welfare             | 등록      | 201       |
| GET    | /api/welfare             | 목록 조회 | 200       |
| GET    | /api/welfare/{id}        | 하나 조회 | 200       |
| PUT    | /api/welfare/{id}        | 수정      | 200       |
| DELETE | /api/welfare/{id}        | 삭제      | 204       |

없는 id를 요청하면 404, 요청 본문이 형식에 안 맞으면 422 (app/schemas.py 검증).

쓰기(등록·수정·삭제)는 관리자만 — 요청 헤더 X-Admin-Token 이 환경변수 ADMIN_TOKEN 과 같아야 한다.
    판정 기준(max_income_ratio 등)을 바꾸면 판정 결과가 바로 바뀌므로 아무나 바꾸면 안 된다.
    ADMIN_TOKEN 이 없으면 쓰기 API 를 끈다 (403). 조회는 누구나.
같은 이름·연도의 제도가 이미 있으면 409 — 판정이 이름으로 제도를 찾으므로 중복되면 결과가 꼬인다.
"""

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select  # SELECT 쿼리를 파이썬 코드로 만드는 함수
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import WelfareProgram
from app.schemas import WelfareProgramCreate, WelfareProgramResponse

# router: 이 파일의 API 묶음. app/main.py 에서 app.include_router(welfare.router) 로 등록된다.
#   prefix → 아래 모든 경로 앞에 "/api/welfare" 가 붙는다.
#   tags   → Swagger(/docs) 화면에서 묶어 보여줄 그룹 이름
router = APIRouter(prefix="/api/welfare", tags=["welfare"])


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """쓰기 API 보호. 토큰은 서버 시작 뒤에 바꿔도 반영되도록 요청마다 환경변수에서 읽는다."""
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "쓰기 API 가 꺼져 있습니다 (서버에 ADMIN_TOKEN 이 설정되지 않음).")
    # compare_digest: 글자를 앞에서부터 비교하다 멈추지 않아, 응답 시간으로 토큰을 알아낼 수 없게 한다
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "관리자 토큰(X-Admin-Token)이 없거나 틀렸습니다.")


def commit_or_409(db: Session) -> None:
    """저장. 같은 이름·연도의 제도가 이미 있으면(unique 제약 위반) 409."""
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "같은 이름·연도의 복지제도가 이미 있습니다.") from e


def find_or_404(db: Session, program_id: int) -> WelfareProgram:
    """id로 복지제도를 찾는다. 없으면 404 에러를 던진다. (조회·수정·삭제에서 공통으로 사용)"""
    program = db.get(WelfareProgram, program_id)  # 기본키(id)로 한 줄 조회. 없으면 None
    if program is None:
        # HTTPException 을 던지면 FastAPI가 {"detail": "..."} 형태의 에러 응답으로 바꿔 준다.
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"복지제도 {program_id}번이 없습니다.")
    return program


# 함수 인자 읽는 법 (아래 API 전부 공통):
#   request: WelfareProgramCreate     → 요청 본문(JSON)을 이 형식으로 검증해서 받음
#   program_id: int                   → 경로의 {program_id} 값을 정수로 받음
#   db: Session = Depends(get_db)     → FastAPI가 DB 세션을 자동으로 열어 넣어 주고, 끝나면 닫음
#   response_model=...                → 반환값을 이 형식으로 변환해 응답 (형식에 없는 칸은 빠짐)


@router.post("", response_model=WelfareProgramResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_program(request: WelfareProgramCreate, db: Session = Depends(get_db)):
    """등록: 요청 본문으로 새 복지제도를 만든다."""
    # model_dump() → 요청 객체를 딕셔너리로 바꿈. ** 로 풀어서 테이블 객체의 칸에 그대로 넣는다.
    program = WelfareProgram(**request.model_dump())
    db.add(program)       # 저장 대기 목록에 올림 (아직 DB엔 안 들어감)
    commit_or_409(db)     # 실제로 DB에 저장
    db.refresh(program)   # DB가 붙여 준 id 등을 다시 읽어 옴
    return program


@router.get("", response_model=list[WelfareProgramResponse])
def list_programs(db: Session = Depends(get_db)):
    """목록 조회: 전체 복지제도를 id 순서로 돌려준다."""
    # SELECT * FROM welfare_programs ORDER BY id
    return db.scalars(select(WelfareProgram).order_by(WelfareProgram.id)).all()


@router.get("/{program_id}", response_model=WelfareProgramResponse)
def get_program(program_id: int, db: Session = Depends(get_db)):
    """하나 조회: id에 해당하는 복지제도. 없으면 404."""
    return find_or_404(db, program_id)


@router.put("/{program_id}", response_model=WelfareProgramResponse, dependencies=[Depends(require_admin)])
def update_program(program_id: int, request: WelfareProgramCreate, db: Session = Depends(get_db)):
    """수정: 기존 복지제도의 모든 칸을 요청 본문 값으로 덮어쓴다. 없으면 404."""
    program = find_or_404(db, program_id)
    # 요청의 칸 이름·값을 하나씩 꺼내 DB 객체에 대입 (program.name = "…", program.category = "…" …)
    for field, value in request.model_dump().items():
        setattr(program, field, value)
    commit_or_409(db)     # 바뀐 내용을 DB에 반영
    db.refresh(program)
    return program


@router.delete("/{program_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_program(program_id: int, db: Session = Depends(get_db)):
    """삭제: id에 해당하는 복지제도를 지운다. 없으면 404. 성공하면 본문 없이 204."""
    program = find_or_404(db, program_id)
    db.delete(program)
    db.commit()
