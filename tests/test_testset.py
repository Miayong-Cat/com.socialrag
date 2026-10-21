"""평가셋·채점 코드 테스트 (대상: evals/testset_2026.json, evals/eval_testset.py).

- 평가셋 모양이 맞는지 (70문항, id, 유형별 필수 칸)
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
from app.eligibility.judge import judge_household
from app.rag.generator import Answer, Source
from evals.eval_testset import full_household, load_items, run_chat, run_engine, run_multiturn, scripted_bot, summarize
from tests.guide_2026 import MEDIAN_2026, PROGRAMS


def judge_without_db(household):
    """app/services/eligibility.judge 와 같은 모양의 결과를 DB 없이 — 지침서 p.14 숫자로 계산."""
    return [
        vars(j) | {"income_ratio": PROGRAMS[j.program], "source_document": "2026 국민기초생활보장 사업안내", "source_page": 14}
        for j in judge_household(household, MEDIAN_2026, PROGRAMS)  # 계산 내역(소득평가액 등)은 엔진이 같이 돌려줌
    ]


def engine_judge(info):
    return judge_without_db(to_household(info))


def test_testset_shape():
    items = load_items()
    assert len(items) == 70
    assert [it["id"] for it in items] == list(range(1, 71))
    assert Counter(it["type"] for it in items) == {"eligibility": 26, "ask": 5, "crisis": 19, "info": 15, "multiturn": 5}
    for it in items:
        if it["type"] == "eligibility":
            assert set(it["expected"]) == set(PROGRAMS) and it["calc"] and it["evidence_pages"]
        if it["type"] == "info":
            assert it["reference"] and it["relevant_pages"]
        if it["type"] == "multiturn":
            assert it["outcome"] in {"judged", "give_up", "answered"} and it["turns"][-1]["ask"] == []
            assert all({"user", "understood", "ask"} <= set(t) for t in it["turns"])
            assert ("expected" in it) == (it["outcome"] == "judged")


def test_hand_calculated_answers_match_engine():
    """손계산 정답(eligibility 26문항) = 판정 엔진 결과. 틀리면 정답이나 엔진 중 하나가 틀린 것.

    multiturn 5문항: 알아듣기 결과(understood)를 정답대로 넣었을 때 되묻기 순서·가정·탈출·중단·판정이 맞는지.
    """
    rows = run_engine(load_items(), judge=engine_judge, search_pages=lambda q: [], judge_household=judge_without_db)
    summary = summarize(rows)
    assert summary["eligibility"] == {"pass": 26, "total": 26}, [r["wrong"] for r in rows if r["type"] == "eligibility" and not r["pass"]]
    assert summary["ask"] == {"pass": 5, "total": 5}
    assert summary["crisis_all"] == {"pass": 70, "total": 70}  # 위기 문항(대응 단계 포함) + 나머지 문항 오탐 없음
    assert summary["crisis"] == {"pass": 19, "total": 19}
    assert summary["multiturn"] == {"pass": 5, "total": 5}, [(r["id"], r["wrong"]) for r in rows if r["type"] == "multiturn" and not r["pass"]]


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
        answer=lambda question, passages, facts, on_text=None: Answer(text="설명", sources=[Source(page=131, section="Ⅲ", quote="30%")]),
    )
    rows = {r["id"]: r for r in run_chat(list(items.values()), Chatbot(deps, log=lambda **_: None))}

    assert rows[2]["pass"] and rows[2]["eligible_ok"] == 4
    assert rows[27]["pass"] and rows[27]["missing"] == ["income", "assets"]   # 되물은 조건
    assert rows[40]["pass"] and rows[40]["cited_pages"] == [131]              # 정답 쪽 인용
    assert rows[40]["contexts"] == ["30% 공제"] and rows[40]["reference"]     # RAGAS 입력


def test_ragas_scores_only_the_explanation():
    """RAGAS 채점 입력: 코드가 붙인 출처 목록·면책 안내와 [p.쪽] 표시는 빼고 Claude 의 설명만 (evals/eval_ragas.py)."""
    from app.chat.format import DISCLAIMER, UNCITED_WARNING, compose
    from evals.eval_ragas import explanation_only

    sources = [{"page": 47, "section": "Ⅱ", "quote": "가구원 및 그 친족이 신청"}]
    text = "가구원이 신청 [p.47]합니다. 공무원도 가능 [p.47, p.48]합니다."
    cleaned = explanation_only(compose(text, sources, None))
    assert cleaned == "가구원이 신청합니다. 공무원도 가능합니다."
    assert DISCLAIMER not in cleaned
    assert explanation_only(compose("설명", [], None)) == "설명"  # 인용이 없으면 출처 대신 경고가 붙음
    assert UNCITED_WARNING not in explanation_only(compose("설명", [], None))


def test_multiturn_scoring_catches_wrong_outcomes():
    """채점이 너무 느슨하지 않은지 — 결과 종류를 바꿔 넣으면 실패해야 한다 (2차 리뷰: 판정 멈춤이 '설명 답'으로 통과했음)."""
    items = {it["id"]: it for it in load_items({52, 55, 56})}

    def score(item, **override):
        it = item | override
        return run_multiturn(it, scripted_bot(it, judge_without_db), "t")

    assert all(score(it)["pass"] for it in items.values())               # 정답대로면 통과
    assert not score(items[56], outcome="answered")["pass"]              # 판정 멈춤 ≠ 설명 답
    assert not score(items[55], outcome="give_up")["pass"]               # 설명 답 ≠ 판정 멈춤
    assert not score(items[52], outcome="answered")["pass"]              # 판정 ≠ 설명 답
    assert not score(items[56], gave_up=["region"])["pass"]              # 멈춘 조건도 비교


def test_multiturn_script_mismatch_and_crisis_per_turn():
    """대본이 흐름과 어긋나면 오류로 멈추지 않고 실패로 기록, 위기 신호는 첫 질문이 아니라 모든 턴에서 잡는다."""
    item = load_items({52})[0]
    short = run_multiturn(item, scripted_bot(item | {"turns": item["turns"][:1]}, judge_without_db), "t")
    assert not short["pass"] and "대본" in short["wrong"][0]

    turns = [item["turns"][0], {"user": "요즘 너무 힘들어서 죽고 싶어요", "understood": {}, "ask": []}]
    row = run_engine([item | {"turns": turns, "outcome": "answered"}], judge=engine_judge,
                     search_pages=lambda q: [], judge_household=judge_without_db)[0]
    assert row["crisis"] == "suicide" and not row["crisis_ok"]          # 2턴의 위기 신호를 잡음 (정답은 위기 없음)
