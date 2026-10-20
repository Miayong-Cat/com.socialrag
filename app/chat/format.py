"""답변 꾸미기 — 판정표·계산 근거·출처·면책 안내를 코드로 만든다.

숫자와 출처는 LLM 이 옮겨 적다 틀리면 안 되므로 전부 여기서 만든다.
Claude 가 쓰는 부분은 "왜 그런지, 다음에 뭘 하면 되는지" 설명뿐이다.

최종 답변 모양 (판정 질문):
    | 급여 | 결과 | 소득인정액 | 선정기준액 |      ← format_judgements
    **계산 근거** …                            ← format_basis
    (Claude 설명)
    **출처** 2026 국민기초생활보장 사업안내 …   ← format_sources (인용이 없으면 UNCITED_WARNING)
    ※ 참고용 1차 판정 …                       ← DISCLAIMER
"""

from app.config import GUIDE_TITLE

INCOME_RECOGNITION_PAGE = 77   # 소득인정액 = 소득평가액 + 재산의 소득환산액 (지침서 쪽)

DISCLAIMER = (
    "※ 이 답변은 AI가 지침서를 바탕으로 만든 **참고용 1차 판정**입니다. "
    "실제 수급 여부는 부양의무자·근로능력 등 추가 조사로 달라질 수 있으니, "
    "주소지 읍·면·동 행정복지센터나 보건복지상담센터(**129**)에서 꼭 확인하세요."
)

UNCITED_WARNING = (
    "※ 이 설명에는 지침서 인용이 없습니다. 지침서에서 근거를 찾지 못했을 수 있으니 관할 기관에 확인하세요."
)


def format_judgements(results: list[dict]) -> str:
    """판정 결과 → 표."""
    lines = ["| 급여 | 결과 | 소득인정액 | 선정기준액 |", "|---|---|---|---|"]
    for r in results:
        mark = "✅ 충족" if r["eligible"] else "❌ 미충족"
        lines.append(f"| {r['program']} | {mark} | {r['recognized_income']:,}원 | {r['threshold']:,}원 |")
    return "\n".join(lines)


def format_basis(results: list[dict]) -> str:
    """판정표 숫자가 어떻게 나왔는지 — 계산식과 근거 쪽.

    재산 환산액은 모든 급여가 같으므로 한 번만 쓰고, 급여마다 소득평가액·선정기준만 쓴다.
    (의료급여는 일반 근로소득 30% 공제가 없어 소득평가액이 다를 수 있다)
    """
    if not results:
        return ""
    lines = [
        f"**계산 근거** — 소득인정액 = 소득평가액 + 재산의 소득환산액 ({GUIDE_TITLE} p.{INCOME_RECOGNITION_PAGE})",
        f"- 재산의 소득환산액: {results[0]['asset_conversion']:,}원",
    ]
    for r in results:
        page = f", p.{r['source_page']}" if r.get("source_page") else ""
        lines.append(
            f"- {r['program']}: 소득평가액 {r['income_evaluation']:,}원 · "
            f"선정기준액 = 기준 중위소득 × {r['income_ratio']:g}%{page}"
        )
    return "\n".join(lines)


def format_sources(sources: list[dict]) -> str:
    """Claude 가 인용한 문장 → 출처 목록 (쪽 순서, 같은 인용은 한 번만). 인용이 없으면 경고."""
    if not sources:
        return UNCITED_WARNING
    seen, lines = set(), []
    for s in sorted(sources, key=lambda s: s["page"]):
        key = (s["page"], s["quote"])
        if key in seen:
            continue
        seen.add(key)
        quote = s["quote"].replace("\n", " ")
        if len(quote) > 80:
            quote = quote[:80] + "…"
        lines.append(f"- p.{s['page']} [{s['section']}] “{quote}”")
    return f"**출처** — {GUIDE_TITLE}\n" + "\n".join(lines)


def compose(explanation: str, sources: list[dict], judgements: list[dict] | None) -> str:
    """최종 답변 = (판정표 + 계산 근거) + 설명 + 출처 + 면책."""
    parts = []
    if judgements:
        parts += [format_judgements(judgements), format_basis(judgements)]
    parts += [explanation, format_sources(sources), DISCLAIMER]
    return "\n\n".join(p for p in parts if p)
