#!/bin/bash
# SessionStart hook, compact matcher. Re-injects task progress lost to compaction.

TODO_DIR=""
for d in ".claude/tasks/todo" "todo"; do
  [ -d "$d" ] && TODO_DIR="$d" && break
done
[ -z "$TODO_DIR" ] && exit 0

TASK_FILES=$(ls "$TODO_DIR"/*.md 2>/dev/null)
[ -z "$TASK_FILES" ] && exit 0

printed=0

for FILE in $TASK_FILES; do
  REMAINING=$(grep -c "\[ \]" "$FILE" 2>/dev/null || echo 0)
  DONE=$(grep -c "\[x\]" "$FILE" 2>/dev/null || echo 0)

  if [ "$REMAINING" -gt 0 ]; then
    if [ "$printed" -eq 0 ]; then
      echo "진행 중인 Task (컨텍스트 재주입)"
      echo ""
      printed=1
    fi
    echo "파일: $FILE"
    echo "  완료 ${DONE}개 / 남음 ${REMAINING}개"
    echo "  다음 작업:"
    grep "\[ \]" "$FILE" | head -3 | sed 's/^/    /'
    echo ""
  fi
done

[ "$printed" -eq 0 ] && exit 0

if [ -f ".claude/.task-running" ]; then
  echo "주의: task-runner 실행 중입니다. 중단 없이 계속 진행하세요."
fi
