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
from app.chat.state import FIELD_LABELS
from app.eligibility.standards import WORK_DEDUCTION_PAGE

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
    근로소득이 있으면 급여마다 근로소득공제액과 그 근거 쪽도 쓴다 —
    의료급여는 일반 근로소득 30% 공제가 없어 소득평가액이 다를 수 있는데, 이유가 안 보이면
    Claude 가 (검색된 문단에 근거가 없을 때) 맞는 판정을 의심하는 설명을 쓰기 때문이다.
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
            f"- {r['program']}: 소득평가액 {r['income_evaluation']:,}원{deduction_note(r)} · "
            f"선정기준액 = 기준 중위소득 × {r['income_ratio']:g}%{page}"
        )
    return "\n".join(lines)


def deduction_note(r: dict) -> str:
    """소득평가액 뒤에 붙일 근로소득공제 설명. 근로소득이 없으면 빈 글."""
    if not r.get("earned_income"):
        return ""
    if r.get("work_deduction"):
        return f" (근로소득 {r['earned_income']:,}원에서 근로소득공제 {r['work_deduction']:,}원을 뺌, p.{WORK_DEDUCTION_PAGE})"
    return f" (일반 근로소득공제 30%는 생계·주거·교육급여에만 있어 {r['program']}에는 적용 안 됨, p.{WORK_DEDUCTION_PAGE})"


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


ASSUMPTION_NOTES = {
    "deduction": (
        "※ 일하시는 분의 공제 유형을 확인하지 못해 **일반(30%) 공제로 가정**하고 계산했어요. "
        "34세 이하·65세 이상·등록장애인·임신 중 등에 해당하면 알려 주세요 — 공제가 커져 결과가 유리해질 수 있어요."
    ),
}


def format_assumptions(assumed: list[str] | None) -> str:
    """답을 못 들어 가정하고 판정한 조건 안내 (app/chat/state.py 의 ASSUMABLE)."""
    return "\n".join(ASSUMPTION_NOTES[f] for f in assumed or [])


def give_up_message(fields: list[str]) -> str:
    """같은 조건을 여러 번 물어도 답을 못 들었을 때 — 판정을 멈추고 무엇이 필요한지 알린다."""
    names = ", ".join(FIELD_LABELS[f] for f in fields)
    return (
        f"{names}을(를) 확인하지 못해 아직 판정할 수 없어요. 알게 되면 언제든 다시 말씀해 주세요 — 바로 이어서 판정해 드릴게요.\n\n"
        "정확한 확인이 어려우면 주소지 읍·면·동 행정복지센터나 보건복지상담센터(**129**)에서 함께 확인할 수 있어요."
    )


def compose(explanation: str, sources: list[dict], judgements: list[dict] | None, assumed: list[str] | None = None) -> str:
    """최종 답변 = (판정표 + 계산 근거 + 가정 안내) + 설명 + 출처 + 면책."""
    parts = []
    if judgements:
        parts += [format_judgements(judgements), format_basis(judgements), format_assumptions(assumed)]
    parts += [explanation, format_sources(sources), DISCLAIMER]
    return "\n\n".join(p for p in parts if p)
