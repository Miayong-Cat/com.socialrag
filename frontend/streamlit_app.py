"""웹 화면 (Streamlit) — 상담 챗봇 · 판정 계산기 · 지침서 검색.

실행 (API 서버를 먼저 켠다):
    uvicorn app.main:app
    streamlit run frontend/streamlit_app.py        → http://localhost:8501
서버 주소를 바꾸려면 환경변수 API_URL (기본 http://127.0.0.1:8000)
색·글꼴 등 테마: .streamlit/config.toml (프로젝트 폴더에서 실행해야 읽힘), 세부 모양: 아래 STYLE

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


STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');
html, body, [class*="st-"], .stMarkdown, button, input, textarea, select { font-family: 'Noto Sans KR', sans-serif; }
.block-container { max-width: 860px; padding-top: 2.5rem; padding-bottom: 6rem; }

/* 머리 */
.hero { padding: 1.6rem 1.8rem; border-radius: 1.2rem; margin-bottom: 1.2rem;
        background: linear-gradient(135deg, #ECF8F6 0%, #F7FBFA 60%, #FFFFFF 100%); border: 1px solid #DCEFEC; }
.hero .badge { display: inline-block; font-size: .78rem; font-weight: 500; color: #0F766E;
               background: #FFFFFF; border: 1px solid #CDE9E5; border-radius: 999px; padding: .15rem .7rem; }
.hero h1 { font-size: 1.75rem; font-weight: 700; color: #12302C; margin: .7rem 0 .35rem; padding: 0; }
.hero p { color: #4A5B59; margin: 0; line-height: 1.6; }

/* 탭 */
.stTabs [data-baseweb="tab-list"] { gap: .4rem; }
.stTabs [data-baseweb="tab"] { font-size: 1rem; padding: .4rem .2rem; }

/* 예시 질문 — 둥근 칩 */
.st-key-examples button { border-radius: 999px; background: #F3FAF9; border: 1px solid #D5ECE8; color: #155E57;
                          font-size: .92rem; padding: .55rem 1rem; text-align: left; justify-content: flex-start; }
.st-key-examples button:hover { background: #E6F5F2; border-color: #0F766E; color: #0F766E; }

/* 대화 말풍선 */
[data-testid="stChatMessage"] { padding: .9rem 1.1rem; border-radius: 1rem; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background: #F1F8F7; }
[data-testid="stChatMessage"] h1, [data-testid="stChatMessage"] h2,
[data-testid="stChatMessage"] h3, [data-testid="stChatMessage"] h4 { font-size: 1.05rem; font-weight: 700; margin: 1rem 0 .3rem; padding: 0; }
[data-testid="stChatMessage"] table { font-size: .92rem; }

.footnote { color: #6B7A78; font-size: .8rem; line-height: 1.6; margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid #E6ECEB; }
</style>
"""

HERO = """
<div class="hero">
  <span class="badge">2026 국민기초생활보장 사업안내 기준</span>
  <h1>복지 급여, 받을 수 있을까요?</h1>
  <p>가구 상황을 편하게 말씀해 주세요. 받을 수 있는 급여를 계산하고, 지침서 근거와 함께 쉽게 설명해 드려요.</p>
</div>
"""

FOOTNOTE = """
<div class="footnote">
  AI가 지침서를 바탕으로 만든 <b>참고용 1차 판정</b>이에요. 부양의무자·근로능력 등 추가 조사로 결과가 달라질 수 있어요.
  최종 확인은 주소지 행정복지센터나 보건복지상담센터 <b>129</b>에서 하세요.
</div>
"""

AVATARS = {"user": "🙂", "assistant": "🤝"}


def header() -> ApiClient:
    """스타일 + 머리. 서버 주소는 환경변수 API_URL 로만 바꾼다 (화면에는 꺼져 있을 때만 안내)."""
    st.markdown(STYLE, unsafe_allow_html=True)
    st.markdown(HERO, unsafe_allow_html=True)
    api = ApiClient(os.environ.get("API_URL", DEFAULT_URL))
    if not api.is_up():
        st.warning(
            "지금은 상담 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.\n\n"
            "(개발자: `uvicorn app.main:app` 으로 API 서버를 켜 주세요)"
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
    with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
        message_body(msg)


def message_body(msg: dict):
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
    prompt = st.chat_input("예: 혼자 사는데 생계급여 받을 수 있나요?")

    with history:
        intro = st.empty()  # 첫 화면 안내 — 질문을 보내면 지운다
        if not st.session_state.messages:
            with intro.container(key="examples"):
                st.markdown("**이렇게 물어보세요**")
                cols = st.columns(2)
                for i, example in enumerate(EXAMPLES):
                    if cols[i % 2].button(example, key=f"example-{i}", use_container_width=True):
                        prompt = example
        elif st.button("↺ 새 대화 시작", key="reset"):
            st.session_state.messages = []
            st.session_state.thread_id = None
            st.rerun()

        for msg in st.session_state.messages:
            show_message(msg)
        if prompt:
            intro.empty()
            send(api, prompt)


def send(api: ApiClient, prompt: str):
    """질문 하나를 보내고 답을 기록·표시한다. 답은 써지는 대로 보여 주다가, 다 오면 완성본으로 바꾼다."""
    show_message({"role": "user", "content": prompt})
    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        box = st.empty()  # 미리 보기 글 → 완성된 답으로 갈아 끼울 자리
        box.caption("지침서를 찾아보고 판정하는 중…")
        preview, data = "", None
        try:
            for event in api.chat_stream(prompt, st.session_state.thread_id):
                if event["type"] == "delta":
                    preview += event["text"]
                    box.markdown(preview + " ▌")
                else:
                    data = event
        except ApiError as e:
            box.error(f"답변을 받지 못했습니다. {e}")
            return  # 실패한 질문은 기록에 남기지 않음 → 다시 보낼 수 있게
        if data is None:
            box.error("답변을 받지 못했습니다. 응답이 중간에 끊겼습니다.")
            return
        st.session_state.thread_id = data["thread_id"]
        answer = {"role": "assistant", "content": data["reply"], "waiting": data["waiting"], "eligibility": data["eligibility"]}
        st.session_state.messages += [{"role": "user", "content": prompt}, answer]
        with box.container():
            message_body(answer)


# ── 탭 2: 판정 계산기 ───────────────────────────────────────


def money(box, label: str, key: str, help: str | None = None) -> int:
    """만원 단위 입력 → 원. box: 입력칸을 놓을 곳 (st 또는 열)"""
    return int(box.number_input(f"{label} (만원)", min_value=0, step=10, key=key, help=help) * MAN)


def calculator_tab(api: ApiClient):
    st.markdown("가구 조건을 넣으면 바로 계산해 드려요. 같은 조건이면 언제나 같은 결과가 나와요.")
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
    st.markdown("상담에서 근거로 쓰는 「국민기초생활보장 사업안내」 지침서를 직접 찾아볼 수 있어요.")
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
    st.set_page_config(page_title="복지 판정 상담", page_icon="🤝", layout="centered")
    api = header()
    chat, calculator, search = st.tabs(["상담하기", "직접 계산하기", "지침서 찾아보기"])
    with chat:
        chat_tab(api)
    with calculator:
        calculator_tab(api)
    with search:
        search_tab(api)
    st.markdown(FOOTNOTE, unsafe_allow_html=True)


main()
