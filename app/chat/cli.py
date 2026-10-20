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
from app.database import create_tables


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 터미널 한글 깨짐 방지
    sys.stdin.reconfigure(encoding="utf-8")
    create_tables()  # 서버를 안 켰어도 ai_search_logs 등 테이블이 있도록
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
        print(f"\n챗봇> {reply.text}\n")  # 출처·면책 안내는 답에 이미 들어 있음 (app/chat/format.py)


if __name__ == "__main__":
    main()
