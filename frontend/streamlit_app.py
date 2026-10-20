"""웹 화면 (Streamlit) — 상담 챗봇 · 판정 계산기 · 지침서 검색.

실행 (API 서버를 먼저 켠다):
    uvicorn app.main:app
    streamlit run frontend/streamlit_app.py        → http://localhost:8501
서버 주소를 바꾸려면 환경변수 API_URL (기본 http://127.0.0.1:8000)

탭별로 필요한 것:
    상담 챗봇    Claude API (ANTHROPIC_API_KEY + 결제) + DB
    판정 계산기  DB 만 — Claude 호출 없음
    지침서 검색  DB + 임베딩 모델 — Claude 호출 없음
"""

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # streamlit run 은 frontend/ 만 경로에 넣으므로
from frontend.api_client import DEFAULT_URL, ApiClient, ApiError  # noqa: E402

# 판정 API 가 받는 값 (app/eligibility/household.py 의 Region·WorkDeduction 과 같아야 함)
REGIONS = ["서울", "경기", "광역·세종·창원", "그 외 지역"]
DEDUCTIONS = {
    "일반": "일반",
    "65세 이상 · 등록장애인 · 35세 이상 학생 (20만원 + 30%)": "20만원 + 30%",
    "34세 이하 · 대학생 (60만원 + 30%)": "60만원 + 30%",
    "임신 중 · 출산 6개월 미만 · 사회복무요원 (30%)": "30% 공제",
    "장애인 직업재활 참여 (20만원 + 50%)": "20만원 + 50%",
}
DEPOSIT_RATE = 0.95  # 주택 임차보증금은 95%로 평가 (지침서 p.164)
MAN = 10_000
EXAMPLES = [
    "혼자 사는데 생계급여 받을 수 있나요?",
    "서울 1인 가구고 월급 110만원, 재산은 없어요. 어떤 급여를 받을 수 있나요?",
    "일해서 번 돈은 얼마나 빼주나요?",
    "아이를 낳으면 받을 수 있는 급여가 있나요?",
]


def won(amount: int) -> str:
    return f"{amount:,}원"


# ── 공통 ────────────────────────────────────────────────────


def sidebar() -> ApiClient:
    with st.sidebar:
        st.header("복지 판정 상담")
        url = st.text_input("API 서버", os.environ.get("API_URL", DEFAULT_URL))
        api = ApiClient(url)
        if api.is_up():
            st.success("서버 연결됨", icon="🟢")
        else:
            st.error("서버에 연결할 수 없습니다.\n\n`uvicorn app.main:app`", icon="🔴")
        if st.button("새 대화 시작", use_container_width=True):
            st.session_state.messages = []
            st.session_state.thread_id = None
        st.divider()
        st.caption(
            "기준: 2026 국민기초생활보장 사업안내\n\n"
            "AI 참고용 1차 판정입니다. 부양의무자·근로능력 등 추가 조사로 결과가 달라질 수 있어요. "
            "최종 확인은 주소지 행정복지센터나 보건복지상담센터 **129**에서 하세요."
        )
    return api


def judgement_table(results: list[dict]) -> pd.DataFrame:
    """판정 결과 → 표 (금액은 보기 좋게 문자열로)."""
    return pd.DataFrame(
        {
            "급여": r["program"],
            "결과": "✅ 충족" if r["eligible"] else "❌ 미충족",
            "소득인정액": won(r["recognized_income"]),
            "선정기준액": won(r["threshold"]),
            "여유(+) / 초과(−)": f"{r['margin']:+,}원",
            "소득평가액": won(r["income_evaluation"]),
            "재산 환산액": won(r["asset_conversion"]),
            "기준": f"중위소득 {r['income_ratio']:g}%",
        }
        for r in results
    )


# ── 탭 1: 상담 챗봇 ─────────────────────────────────────────


def show_message(msg: dict):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])  # 판정표·계산 근거·출처·면책 안내가 이미 들어 있음 (app/chat/format.py)
        if msg.get("eligibility"):
            with st.expander("판정 계산 상세"):
                st.dataframe(judgement_table(msg["eligibility"]), hide_index=True)
        if msg.get("waiting"):
            st.caption("💬 위 질문에 답해 주시면 이어서 판정합니다.")


def chat_tab(api: ApiClient):
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("thread_id", None)

    # 탭 안의 chat_input 은 부른 자리에 그려진다 → 대화 기록 자리를 먼저 잡아 두고 입력창은 그 아래에
    history = st.container()
    prompt = st.chat_input("궁금한 것을 물어보세요")

    with history:
        if not st.session_state.messages:
            st.markdown("기초생활보장 급여를 **받을 수 있는지** 판정하고, 제도를 **지침서 근거와 함께** 설명해 드려요.")
            cols = st.columns(2)
            for i, example in enumerate(EXAMPLES):
                if cols[i % 2].button(example, key=f"example-{i}", use_container_width=True):
                    prompt = example

        for msg in st.session_state.messages:
            show_message(msg)
        if prompt:
            send(api, prompt)


def send(api: ApiClient, prompt: str):
    """질문 하나를 보내고 답을 기록·표시한다."""
    show_message({"role": "user", "content": prompt})
    with st.spinner("지침서를 찾아보고 판정하는 중…"):
        try:
            data = api.chat(prompt, st.session_state.thread_id)
        except ApiError as e:
            st.error(f"답변을 받지 못했습니다. {e}")
            return  # 실패한 질문은 기록에 남기지 않음 → 다시 보낼 수 있게
    st.session_state.thread_id = data["thread_id"]
    answer = {"role": "assistant", "content": data["reply"], "waiting": data["waiting"], "eligibility": data["eligibility"]}
    st.session_state.messages += [{"role": "user", "content": prompt}, answer]
    show_message(answer)


# ── 탭 2: 판정 계산기 ───────────────────────────────────────


def money(box, label: str, key: str, help: str | None = None) -> int:
    """만원 단위 입력 → 원. box: 입력칸을 놓을 곳 (st 또는 열)"""
    return int(box.number_input(f"{label} (만원)", min_value=0, step=10, key=key, help=help) * MAN)


def calculator_tab(api: ApiClient):
    st.markdown("가구 조건을 넣으면 **판정 엔진**이 바로 계산합니다. (Claude 호출 없음 — 같은 입력이면 항상 같은 결과)")
    with st.form("calculator"):
        c1, c2 = st.columns(2)
        size = c1.number_input("가구원 수 (본인 포함)", min_value=1, max_value=20, value=1, key="size")
        region = c2.selectbox("거주 지역", REGIONS, key="region", help="광역시·세종·창원은 '광역·세종·창원', 그 밖의 시·군은 '그 외 지역'")

        st.subheader("소득 (월)")
        c1, c2 = st.columns(2)
        earned = money(c1, "근로·사업소득", "earned", help="가구 전체 합계")
        deduction = c2.selectbox("근로소득자 공제 유형", list(DEDUCTIONS), key="deduction")
        other = money(c1, "그 밖의 소득", "other", help="연금·임대료·이자 등 — 근로소득공제를 받지 않는 소득")

        st.subheader("재산")
        c1, c2 = st.columns(2)
        housing = money(c1, "사는 집", "housing", help="자가면 집 가액, 전·월세면 보증금")
        rented = c1.checkbox("전·월세 보증금입니다 (95%로 평가, p.164)", key="rented")
        general = money(c1, "그 밖의 토지·건물", "general")
        financial = money(c2, "예금·적금·주식·보험", "financial", help="가구당 500만원은 빼고 계산 (p.174)")
        car = money(c2, "승용차 가액", "car", help="생업용·장애인 사용 자동차가 아닌 일반 승용차 — 월 100% 환산")
        debt = money(c2, "대출 등 부채", "debt")
        submitted = st.form_submit_button("판정하기", type="primary", use_container_width=True)

    if not submitted:
        return
    household = {
        "size": int(size),
        "region": region,
        "earners": [{"monthly_income": earned, "deduction": DEDUCTIONS[deduction]}] if earned else [],
        "other_income": other,
        "housing": int(housing * DEPOSIT_RATE) if rented else housing,
        "general": general,
        "financial": financial,
        "car_full_rate": car,
        "debt": debt,
    }
    try:
        data = api.judge(household)
    except ApiError as e:
        st.error(f"판정하지 못했습니다. {e}")
        return

    results = data["results"]
    cols = st.columns(len(results))
    for col, r in zip(cols, results):
        col.metric(
            r["program"],
            "충족" if r["eligible"] else "미충족",
            f"{r['margin']:+,}원",
            delta_color="normal",  # 여유(+)는 초록, 초과(−)는 빨강
        )
    st.dataframe(judgement_table(results), hide_index=True)
    st.caption(
        "소득인정액 = 소득평가액 + 재산의 소득환산액 (p.77) · 선정기준액 = 기준 중위소득 × 급여별 비율 (p.14) · "
        "부양의무자 기준은 판정하지 않습니다."
    )


# ── 탭 3: 지침서 검색 ───────────────────────────────────────


def search_tab(api: ApiClient):
    st.markdown("챗봇이 답변 근거로 쓰는 것과 같은 검색입니다. (Claude 호출 없음)")
    c1, c2 = st.columns([4, 1])
    query = c1.text_input("검색어", placeholder="예: 근로소득 공제, 자동차 재산, 해산급여", key="query")
    k = c2.number_input("개수", min_value=1, max_value=20, value=5, key="k")
    if not query:
        return
    with st.spinner("검색 중…"):
        try:
            passages = api.search(query, int(k))
        except ApiError as e:
            st.error(f"검색하지 못했습니다. {e}")
            return
    for rank, p in enumerate(passages, start=1):
        title = f"{rank}. p.{p['page']} · {p['section']}" + (f" > {p['heading']}" if p["heading"] else "")
        with st.expander(title, expanded=rank == 1):
            st.text(p["text"])


def main():
    st.set_page_config(page_title="복지 판정 상담", page_icon="🏛️", layout="wide")
    api = sidebar()
    chat, calculator, search = st.tabs(["💬 상담 챗봇", "🧮 판정 계산기", "🔎 지침서 검색"])
    with chat:
        chat_tab(api)
    with calculator:
        calculator_tab(api)
    with search:
        search_tab(api)


main()
