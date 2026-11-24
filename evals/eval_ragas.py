"""RAGAS 채점 — 설명 질문(info) 15문항의 답변을 Faithfulness · Answer Relevancy · Context Precision 으로 잰다.

입력: evals/results/testset_chat.json (먼저 `python -m evals.eval_testset --chat` 실행)
    info 문항마다 저장된 질문 · 답변 · 검색 문맥(contexts, 5개) · 참고 답변(reference)

지표 (0~1, 높을수록 좋음 — RAGAS 의 정의·프롬프트를 그대로 쓴다):
    faithfulness       답변을 주장 단위로 쪼개, 검색 문맥으로 뒷받침되는 주장의 비율 → 지어낸 말이 없나
    answer_relevancy   답변만 보고 질문을 거꾸로 3개 만들어, 원래 질문과의 임베딩 유사도 평균 → 동문서답이 아닌가
    context_precision  검색 문맥 5개가 참고 답변에 쓸모 있는지 하나씩 판단해 등수 가중 평균 → 쓸모 있는 문단이 위에 왔나

채점자 LLM: JUDGE_MODEL (답변을 만든 모델과 다른 모델 — 자기 답에 후한 점수를 주는 편향을 줄이려고)
임베딩: 검색과 같은 BGE-m3 (answer_relevancy 의 질문 유사도 계산용, 로컬 실행)

왜 RAGAS 의 llm_factory 를 안 쓰나:
    RAGAS 가 요구하는 것은 "프롬프트 + 출력 모양 → 구조화된 답" 한 가지뿐이라,
    그 부분만 OllamaJudge 로 직접 구현해 끼운다. 지표 계산(프롬프트·점수식)은 RAGAS 코드 그대로다.

사용법 (Ollama 실행 + `ollama pull exaone3.5:7.8b` — 무료, 15문항 1회 로컬 호출 약 150번이라 오래 걸림):
    python -m evals.eval_ragas
    python -m evals.eval_ragas --ids 36,37      일부 문항만 (결과 파일은 덮지 않음)
결과: evals/results/ragas.json
"""

import argparse
import asyncio
import json
import re
import sys

from evals.eval_testset import RESULTS_DIR

JUDGE_MODEL = "exaone3.5:7.8b"
METRICS = ("faithfulness", "answer_relevancy", "context_precision")
SOURCES_HEADER = "**출처**"


def explanation_only(answer: str) -> str:
    """챗봇 답 → LLM 이 쓴 설명만. 코드가 붙인 출처 목록·면책 안내(app/chat/format.py)와 [p.쪽] 표시는 뺀다.

    출처·면책은 지침서 문맥에 없는 문장이라 faithfulness 를 억울하게 깎고, 채점 대상(LLM 의 설명)도 아니다.
    """
    from app.chat.format import UNCITED_WARNING

    for marker in (f"\n\n{SOURCES_HEADER}", f"\n\n{UNCITED_WARNING}"):
        if marker in answer:
            answer = answer[: answer.index(marker)]
    return re.sub(r" ?\[p\.\d+(?:, p\.\d+)*\]", "", answer).strip()


def make_judge():
    """RAGAS 지표에 끼울 채점자 LLM. ragas 를 import 해야 해서 함수 안에서 클래스를 만든다 (테스트·engine 모드가 ragas 없이 돌게)."""
    import ollama
    from ragas.llms.base import InstructorBaseRagasLLM

    from app.config import LLM_CONTEXT_TOKENS, LLM_TIMEOUT, OLLAMA_HOST

    class OllamaJudge(InstructorBaseRagasLLM):
        """RAGAS 프롬프트 → Ollama 구조화 출력(format) → RAGAS 가 요구한 Pydantic 모양."""

        def __init__(self, model: str):
            self.model = model
            self.client = ollama.AsyncClient(host=OLLAMA_HOST, timeout=LLM_TIMEOUT)

        async def agenerate(self, prompt, response_model):
            response = await self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format=response_model.model_json_schema(),
                options={"temperature": 0, "num_ctx": LLM_CONTEXT_TOKENS},
            )
            return response_model.model_validate_json(response.message.content)

        def generate(self, prompt, response_model):
            return asyncio.run(self.agenerate(prompt, response_model))

    return OllamaJudge(JUDGE_MODEL)


async def score_rows(rows: list[dict]) -> list[dict]:
    """info 문항마다 지표 3개를 채점한다. 한 문항의 지표 3개는 동시에, 문항은 하나씩 (호출 한도 보호)."""
    from ragas.embeddings.huggingface_provider import HuggingFaceEmbeddings
    from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, Faithfulness

    from app.config import EMBEDDING_MODEL

    judge = make_judge()
    faithfulness = Faithfulness(llm=judge)
    relevancy = AnswerRelevancy(llm=judge, embeddings=HuggingFaceEmbeddings(model=EMBEDDING_MODEL, device="cpu"))
    precision = ContextPrecision(llm=judge)

    scored = []
    for r in rows:
        answer = explanation_only(r["answer"])
        values = await asyncio.gather(
            faithfulness.ascore(user_input=r["question"], response=answer, retrieved_contexts=r["contexts"]),
            relevancy.ascore(user_input=r["question"], response=answer),
            precision.ascore(user_input=r["question"], reference=r["reference"], retrieved_contexts=r["contexts"]),
        )
        row = {"id": r["id"], "question": r["question"]} | {m: round(v.value, 3) for m, v in zip(METRICS, values)}
        print(f"Q{row['id']:<3}" + "  ".join(f"{m} {row[m]:.2f}" for m in METRICS) + f"  {r['question'][:30]}")
        scored.append(row)
    return scored


def summarize(scored: list[dict]) -> dict:
    """지표별 평균."""
    return {m: round(sum(r[m] for r in scored) / len(scored), 3) for m in METRICS}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="RAGAS 채점 (info 문항)")
    parser.add_argument("--ids", help="일부 문항만 (쉼표로 구분한 id)")
    args = parser.parse_args()

    source = RESULTS_DIR / "testset_chat.json"
    if not source.exists():
        sys.exit(f"{source} 가 없습니다. 먼저 `python -m evals.eval_testset --chat` 을 실행하세요.")
    ids = {int(i) for i in args.ids.split(",")} if args.ids else None
    rows = [r for r in json.loads(source.read_text(encoding="utf-8"))["rows"]
            if r["type"] == "info" and (ids is None or r["id"] in ids)]

    scored = asyncio.run(score_rows(rows))
    summary = summarize(scored)
    print(f"\n[RAGAS] info 문항 {len(scored)}개 · 채점자 {JUDGE_MODEL}")
    for m in METRICS:
        print(f"  {m:<18} {summary[m]:.3f}")
    if ids is None:
        path = RESULTS_DIR / "ragas.json"
        path.write_text(json.dumps({"judge": JUDGE_MODEL, "summary": summary, "rows": scored}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"저장: {path}")


if __name__ == "__main__":
    main()
