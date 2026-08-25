#!/bin/bash
# PostToolUse hook. Warns when a module other than the shared fetch client calls an
# HTTP library directly. rules/crawling.md: every outbound request goes through one client.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

case "$FILE_PATH" in
  *.py) ;;
  *) exit 0 ;;
esac

# The client itself is the one place allowed to do this.
case "$FILE_PATH" in
  *app/crawler/fetcher.py) exit 0 ;;
  # 우리가 운영하는 알림 서버로 나간다. robots 를 물을 상대가 아니고 지킬 딜레이도
  # 없다 (.claude/rules/crawling.md 의 One fetch client).
  *app/notify/*.py) exit 0 ;;
  *tests/*) exit 0 ;;
esac

HITS=$(grep -nE '\b(httpx|requests)\.(get|post|request|Client|AsyncClient)\b' "$FILE_PATH" 2>/dev/null)

if [ -n "$HITS" ]; then
  echo "$FILE_PATH: HTTP 라이브러리를 직접 호출하고 있습니다. 공용 fetch 클라이언트(app/crawler/fetcher.py)를 쓰세요 — .claude/rules/crawling.md"
  echo "$HITS"
fi

exit 0
