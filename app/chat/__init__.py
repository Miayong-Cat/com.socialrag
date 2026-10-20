"""대화형 챗봇 (6단계, LangGraph) — 조건을 되묻고 판정까지 한다. 구조는 app/chat/graph.py 맨 위 그림 참고.

| 파일          | 하는 일                                                   |
|---------------|-----------------------------------------------------------|
| state.py      | 대화 상태(ChatState), 가구 조건(HouseholdInfo)·수집 규칙    |
| understand.py | 사용자 말 → 의도·조건·검색어 (Claude 구조화 출력)           |
| graph.py      | LangGraph 그래프 — 노드와 분기, 되묻기 루프                  |
| session.py    | 메시지 하나 처리 (되묻는 중이면 답으로 이어서 실행)          |
| cli.py        | 터미널 대화 (python -m app.chat.cli)                        |
"""
