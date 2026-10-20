"""터미널에서 챗봇과 대화하기.

사용법:
    python -m app.chat.cli
필요한 것:
    - DB 실행 + 기준 중위소득·청크 적재 (README "데이터 적재")
    - .env 에 ANTHROPIC_API_KEY
끝내려면 빈 줄에서 Enter 또는 Ctrl+C.
"""

import sys
import uuid

from app.chat.session import Chatbot


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 터미널 한글 깨짐 방지
    sys.stdin.reconfigure(encoding="utf-8")
    bot = Chatbot()
    thread_id = uuid.uuid4().hex  # 이 대화의 번호 — 같은 번호로 보내면 앞 대화의 조건이 이어짐
    print("국민기초생활보장 상담 챗봇입니다. 궁금한 것을 물어보세요. (끝내려면 빈 줄에서 Enter)\n")

    while True:
        try:
            message = input("나> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message:
            break
        reply = bot.send(thread_id, message)
        print(f"\n챗봇> {reply.text}\n")
        if reply.sources:
            pages = sorted({s["page"] for s in reply.sources})
            print(f"(근거: 2026 국민기초생활보장 사업안내 {', '.join(f'p.{p}' for p in pages)})\n")


if __name__ == "__main__":
    main()
