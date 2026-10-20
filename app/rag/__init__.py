"""RAG(검색 증강 생성) — 지침서에서 근거 문단을 찾아 Claude 가 설명하게 한다. (4단계)

판정(수급 가능 여부)은 app/eligibility/ 가 코드로 계산하고, 여기는 "왜 그런지"를 지침서로 설명하는 부분이다.

| 파일          | 하는 일                                                          |
|---------------|------------------------------------------------------------------|
| chunking.py   | 쪽별 본문 → 검색 단위 조각(청크). 머리말·쪽번호 제거, 장 이름 헤더 |
| embedding.py  | 글 → 벡터 (BGE-m3, 로컬)                                          |
| retriever.py  | 질문과 가까운 청크 검색 (pgvector 코사인 거리)                    |
| generator.py  | 청크를 근거로 Claude 가 답변 + 인용 쪽번호                          |
| ask.py        | 터미널에서 질문해 보는 CLI                                         |

흐름:
    [적재, 한 번]  text_2026.jsonl → chunking → embedding → guide_chunks 테이블  (ingestion/load_chunks.py)
    [질문할 때]    질문 → embedding → retriever(가까운 청크 k개) → generator(Claude) → 답변 + 근거 쪽
"""
