#!/usr/bin/env bash
# Start the Claude Code scheduled task right away (its API trigger), so work begins as soon as there is
# usage left instead of waiting for the hourly run. Needs repo secrets CLAUDE_TASK_URL (the task's
# "Fire URL") and CLAUDE_TASK_TOKEN. Never fails the workflow: without them, or when Claude is out of usage,
# the hourly run picks the work up.   Usage: scripts/wake_claude.sh "<why>"
set -u
[ -n "${CLAUDE_TASK_URL:-}" ] && [ -n "${CLAUDE_TASK_TOKEN:-}" ] || {
  echo "::warning::Chưa cài CLAUDE_TASK_URL/CLAUDE_TASK_TOKEN: chưa gọi Claude ngay được, phiếu chờ lượt chạy mỗi giờ."
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '\n### Chưa gọi được Claude ngay\nThêm secrets `CLAUDE_TASK_URL` và `CLAUDE_TASK_TOKEN` (API trigger của tác vụ Claude cho repo này) để Claude bắt đầu ngay khi có việc. Hiện phiếu chờ lượt chạy mỗi giờ.\n' >> "$GITHUB_STEP_SUMMARY"
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
  *)  echo "::warning::wake: gọi Claude không được (HTTP $CODE) — lượt hằng giờ sẽ làm"; head -c 300 /tmp/wake.json; echo ;;
esac
exit 0
