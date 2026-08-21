#!/bin/bash
# Stop hook. Keeps Claude working while a task-runner session has unfinished items.
# Only active while the .claude/.task-running sentinel exists.

INPUT=$(cat)

[ ! -f ".claude/.task-running" ] && exit 0

# stop_hook_active guards against an infinite stop loop.
if [ "$(echo "$INPUT" | jq -r '.stop_hook_active')" = "true" ]; then
  exit 0
fi

TODO_DIR=""
for d in ".claude/tasks/todo" "todo"; do
  [ -d "$d" ] && TODO_DIR="$d" && break
done
[ -z "$TODO_DIR" ] && exit 0

REMAINING=$(grep -l "\[ \]" "$TODO_DIR"/*.md 2>/dev/null | head -1)

if [ -n "$REMAINING" ]; then
  COUNT=$(grep -c "\[ \]" "$REMAINING" 2>/dev/null || echo "?")
  echo "{\"decision\": \"block\", \"reason\": \"$REMAINING 에 미완료 작업 ${COUNT}개 남음. 모든 [ ] 항목을 [x] 로 완료하기 전까지 계속 실행하세요. 사용자 확인 없이 자율적으로 진행합니다.\"}"
fi

exit 0
