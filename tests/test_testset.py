"""평가셋·채점 코드 테스트 (대상: evals/testset_2026.json, evals/eval_testset.py).

- 평가셋 모양이 맞는지 (50문항, id, 유형별 필수 칸)
- 손계산 정답이 판정 엔진과 맞는지 — DB 대신 지침서 표 숫자(tests/guide_2026.py)로 계산
- chat 모드 채점이 챗봇 답을 제대로 읽는지 — Claude·DB 대신 가짜 의존성

실행:
    pytest tests/test_testset.py
"""

from collections import Counter

from app.chat.graph import Deps
from app.chat.session import Chatbot
from app.chat.state import to_household
from app.chat.understand import Understanding
from app.eligibility.asset import asset_conversion
from app.eligibility.income import income_evaluation
from app.eligibility.judge import judge_household
from app.rag.generator import Answer, Source
from evals.eval_testset import full_household, load_items, run_chat, run_engine, summarize
from tests.guide_2026 import MEDIAN_2026, PROGRAMS


def judge_without_db(household):
    """app/services/eligibility.judge 와 같은 모양의 결과를 DB 없이 — 지침서 p.14 숫자로 계산."""
    return [
        vars(j) | {
            "income_ratio": PROGRAMS[j.program],
            "income_evaluation": income_evaluation(household, j.program),
            "asset_conversion": asset_conversion(household),
            "source_document": "2026 국민기초생활보장 사업안내",
            "source_page": 14,
        }
        for j in judge_household(household, MEDIAN_2026, PROGRAMS)
    ]


def engine_judge(info):
    return judge_without_db(to_household(info))


def test_testset_shape():
    items = load_items()
    assert len(items) == 50
    assert [it["id"] for it in items] == list(range(1, 51))
    assert Counter(it["type"] for it in items) == {"eligibility": 25, "ask": 5, "crisis": 5, "info": 15}
    for it in items:
        if it["type"] == "eligibility":
            assert set(it["expected"]) == set(PROGRAMS) and it["calc"] and it["evidence_pages"]
        if it["type"] == "info":
            assert it["reference"] and it["relevant_pages"]


def test_hand_calculated_answers_match_engine():
    """손계산 정답(eligibility 25문항) = 판정 엔진 결과. 틀리면 정답이나 엔진 중 하나가 틀린 것."""
    rows = run_engine(load_items(), judge=engine_judge, search_pages=lambda q: [])
    summary = summarize(rows)
    assert summary["eligibility"] == {"pass": 25, "total": 25}, [r["wrong"] for r in rows if r["type"] == "eligibility" and not r["pass"]]
    assert summary["ask"] == {"pass": 5, "total": 5}
    assert summary["crisis_all"] == {"pass": 50, "total": 50}  # 위기 문항 + 나머지 45문항 오탐 없음


def test_chat_mode_scoring():
    """chat 모드: 알아들은 조건 → 판정 → 채점. 가짜 Claude 가 정답 가구를 그대로 알아들었다고 가정."""
    items = {it["id"]: it for it in load_items({2, 27, 40})}
    understood = {
        items[2]["question"]: Understanding(intent="eligibility", household=full_household(items[2]), search_query="q"),
        items[27]["question"]: Understanding(intent="eligibility", household=items[27]["household"], search_query="q"),
        items[40]["question"]: Understanding(intent="info", household={}, search_query="근로소득 공제"),
    }
    deps = Deps(
        understand=lambda messages, known, asked: understood[messages[-1]["content"]],
        search=lambda query: [{"page": 131, "section": "Ⅲ. 소득조사", "heading": "", "text": "30% 공제"}],
        judge=judge_without_db,
        answer=lambda question, passages, facts: Answer(text="설명", sources=[Source(page=131, section="Ⅲ", quote="30%")]),
    )
    rows = {r["id"]: r for r in run_chat(list(items.values()), Chatbot(deps, log=lambda **_: None))}

    assert rows[2]["pass"] and rows[2]["eligible_ok"] == 4
    assert rows[27]["pass"] and rows[27]["missing"] == ["income", "assets"]   # 되물은 조건
    assert rows[40]["pass"] and rows[40]["cited_pages"] == [131]              # 정답 쪽 인용
    assert rows[40]["contexts"] == ["30% 공제"] and rows[40]["reference"]     # RAGAS 입력
