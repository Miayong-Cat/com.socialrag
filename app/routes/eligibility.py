"""판정 API — 가구 정보를 받아 제도별 수급 가능 여부를 계산해 돌려준다.

| 메서드 | 경로              | 하는 일 | 성공 코드 |
|--------|-------------------|---------|-----------|
| POST   | /api/eligibility  | 판정    | 200       |

이 파일은 "요청 받기 + 서비스 부르기"만 한다.
DB 조회와 판정은 app/services/eligibility.py (챗봇과 같이 씀), 계산은 app/eligibility/ 가 맡는다.

그 연도의 기준 중위소득이 DB에 없으면 404 (적재 스크립트를 먼저 실행해야 함).
요청 본문이 형식에 안 맞으면 422 (app/schemas.py 검증).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import EligibilityRequest, EligibilityResponse
from app.services import eligibility as service

router = APIRouter(prefix="/api/eligibility", tags=["eligibility"])


@router.post("", response_model=EligibilityResponse)
def judge_eligibility(request: EligibilityRequest, db: Session = Depends(get_db)):
    """판정: 가구 정보로 그 연도의 모든 제도에 대해 충족 여부와 계산 내역을 돌려준다."""
    household = request.to_household()
    try:
        results = service.judge(db, household, request.year)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return EligibilityResponse(year=request.year, household_size=household.size, results=results)
