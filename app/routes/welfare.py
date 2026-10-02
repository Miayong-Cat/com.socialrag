"""복지제도 CRUD API. (자바로 치면 @RestController)

| 메서드 | 경로                     | 하는 일   |
|--------|--------------------------|-----------|
| POST   | /api/welfare             | 등록      |
| GET    | /api/welfare             | 목록 조회 |
| GET    | /api/welfare/{id}        | 하나 조회 |
| PUT    | /api/welfare/{id}        | 수정      |
| DELETE | /api/welfare/{id}        | 삭제      |
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import WelfareProgram
from app.schemas import WelfareProgramCreate, WelfareProgramResponse

router = APIRouter(prefix="/api/welfare", tags=["welfare"])


def find_or_404(db: Session, program_id: int) -> WelfareProgram:
    program = db.get(WelfareProgram, program_id)
    if program is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"복지제도 {program_id}번이 없습니다.")
    return program


@router.post("", response_model=WelfareProgramResponse, status_code=status.HTTP_201_CREATED)
def create_program(request: WelfareProgramCreate, db: Session = Depends(get_db)):
    program = WelfareProgram(**request.model_dump())
    db.add(program)
    db.commit()
    db.refresh(program)
    return program


@router.get("", response_model=list[WelfareProgramResponse])
def list_programs(db: Session = Depends(get_db)):
    return db.scalars(select(WelfareProgram).order_by(WelfareProgram.id)).all()


@router.get("/{program_id}", response_model=WelfareProgramResponse)
def get_program(program_id: int, db: Session = Depends(get_db)):
    return find_or_404(db, program_id)


@router.put("/{program_id}", response_model=WelfareProgramResponse)
def update_program(program_id: int, request: WelfareProgramCreate, db: Session = Depends(get_db)):
    program = find_or_404(db, program_id)
    for field, value in request.model_dump().items():
        setattr(program, field, value)
    db.commit()
    db.refresh(program)
    return program


@router.delete("/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_program(program_id: int, db: Session = Depends(get_db)):
    program = find_or_404(db, program_id)
    db.delete(program)
    db.commit()
