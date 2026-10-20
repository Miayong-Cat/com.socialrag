"""DB 테이블 정의 모음 — 테이블 하나 = 파일 하나.

| 파일                 | 테이블             | 내용                              |
|----------------------|--------------------|-----------------------------------|
| welfare_program.py   | welfare_programs   | 복지제도 (이름, 중위소득 대비 비율 …) |
| median_income.py     | median_incomes     | 연도·가구원 수별 기준 중위소득       |
| guide_chunk.py       | guide_chunks       | 지침서 본문 조각 + 임베딩 (RAG)      |
| ai_search_log.py     | ai_search_logs     | 챗봇 대화 한 턴 기록 (응답 시간 등)  |

이 파일이 하는 일:
    1. 다른 파일에서 짧게 꺼내 쓸 수 있게 해 준다.
         from app.models import WelfareProgram   (O)
         from app.models.welfare_program import WelfareProgram   (이렇게 길게 안 써도 됨)
    2. 모든 테이블 클래스를 여기서 import 해 두면, app.models 를 한 번 import 하는 것만으로
       Base.metadata 에 모든 테이블이 등록된다 → create_all 이 빠짐없이 테이블을 만든다.

테이블을 새로 추가하면:
    1. 이 폴더에 파일을 만들고 Base 를 상속한 클래스를 정의한다. (기존 파일을 본보기로)
    2. 아래 import 와 __all__ 에 한 줄씩 추가한다. ← 빠뜨리면 테이블이 생성되지 않는다!
    3. README.md 의 "DB 테이블" 표에도 한 줄 추가한다.
"""

from app.models.ai_search_log import AiSearchLog
from app.models.guide_chunk import GuideChunk
from app.models.median_income import MedianIncome
from app.models.welfare_program import WelfareProgram

# __all__ = "from app.models import *" 했을 때 꺼내지는 이름 목록 (이 패키지가 공개하는 테이블 목록)
__all__ = ["AiSearchLog", "GuideChunk", "MedianIncome", "WelfareProgram"]
