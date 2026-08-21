#!/bin/bash
# PostToolUse hook. Formats and lints a Python file right after Claude writes it.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

case "$FILE_PATH" in
  *.py) ;;
  *) exit 0 ;;
esac

ruff format "$FILE_PATH" 2>/dev/null || true
ruff check --fix "$FILE_PATH" 2>/dev/null || true
