#!/usr/bin/env bash
# Start the Claude Code task right away (its API trigger). This is the only way Claude starts on its own: there is
# no hourly run. Needs repo secrets CLAUDE_TASK_URL (the task's
# "Fire URL") and CLAUDE_TASK_TOKEN. Never fails the workflow: without them, or when Claude is out of usage,
# the issue waits until the owner presses "Gọi Claude ngay" or works in a chat.   Usage: scripts/wake_claude.sh "<why>"
set -u
[ -n "${CLAUDE_TASK_URL:-}" ] && [ -n "${CLAUDE_TASK_TOKEN:-}" ] || {
  echo "::warning::Chưa cài CLAUDE_TASK_URL/CLAUDE_TASK_TOKEN: chưa gọi được Claude. Phiếu chờ đến khi thêm hai secret này rồi bấm Gọi Claude ngay, hoặc làm trong chat."
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '\n### Chưa gọi được Claude ngay\nThêm secrets `CLAUDE_TASK_URL` và `CLAUDE_TASK_TOKEN` (API trigger của tác vụ Claude cho repo này) để Claude bắt đầu ngay khi có việc. Không có lượt chạy mỗi giờ: hiện phiếu chờ đến khi bấm **Gọi Claude ngay** hoặc làm trong chat.\n' >> "$GITHUB_STEP_SUMMARY"
  fi
  exit 0
}
WHY=$(printf '%s' "${1:-}" | python3 -c 'import json,sys;print(json.dumps({"text":sys.stdin.read()[:300]}))')
CODE=$(curl -s -o /tmp/wake.json -w '%{http_code}' --max-time 30 -X POST "$CLAUDE_TASK_URL" \
  -H "Authorization: Bearer $CLAUDE_TASK_TOKEN" \
  -H "anthropic-beta: experimental-cc-routine-2026-04-01" -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" -d "$WHY")
case "$CODE" in
  2*) echo "wake: Claude đã được gọi ($(python3 -c "import json;print(json.load(open('/tmp/wake.json')).get('claude_code_session_url',''))" 2>/dev/null))" ;;
  *)  echo "::warning::wake: gọi Claude không được (HTTP $CODE) — bấm Gọi Claude ngay sau, hoặc làm trong chat"; head -c 300 /tmp/wake.json; echo ;;
esac
exit 0
