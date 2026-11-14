#!/usr/bin/env bash
# Start the Claude Code task right away (its API trigger). This is the only way Claude starts on its own: there is
# no hourly run. Needs repo secrets CLAUDE_TASK_URL (the task's "Fire URL") and CLAUDE_TASK_TOKEN.
#
# Usage: scripts/wake_claude.sh "<why>" [<issue> ["<facts>" ["<promise>"]]]
#   <issue>    the issue the call is about. With it (and GH_TOKEN + GITHUB_REPOSITORY for gh):
#              - an issue that carries a lore-busy label added less than 2 hours ago is being worked on (a chat or
#                another run of the task): Claude is not called again;
#              - when Claude could not be called, the issue gets a 🤖 comment telling the owner to press
#                "Gọi Claude ngay".
#   <facts>    what the machine did, posted on the issue as one comment. <promise> ("Claude sẽ …") is added only when
#              Claude was called or already has the issue; otherwise the "could not call Claude" hint takes its place,
#              so a machine comment never promises work that nobody was woken for.
# The call is tried 3 times (network errors, 429, 5xx). Never fails the workflow: always exits 0.
set -u
WHY=${1:-}
N=${2:-}
FACTS=${3:-}
PROMISE=${4:-}
BACKOFF=${WAKE_BACKOFF:-10}          # seconds before the 2nd try; twice that before the 3rd
OUT=$(mktemp)
REPO=${GITHUB_REPOSITORY:-${GH_REPO:-}}
BUTTON="${GITHUB_SERVER_URL:-https://github.com}/$REPO/actions/workflows/wake.yml"
HINT="Chưa gọi được Claude nên phiếu đang chờ ở bước này. Mở $BUTTON , bấm **Run workflow** để gọi Claude (hoặc mở một chat với Claude)."

can_comment() { [ -n "$N" ] && [ -n "$REPO" ] && [ -n "${GH_TOKEN:-}" ]; }

say() {   # one comment on the issue; never fails
  can_comment || return 0
  gh api -X POST "repos/$REPO/issues/$N/comments" -f body="$1" > /dev/null \
    || echo "::warning::wake: không viết được bình luận vào phiếu $N"
}

fresh_busy() {   # true when the issue has lore-busy and it was added less than 2 hours ago
  can_comment || return 1
  gh api "repos/$REPO/issues/$N" --jq '.labels[].name' 2>/dev/null | grep -qx 'lore-busy' || return 1
  local at
  at=$(gh api --paginate "repos/$REPO/issues/$N/events?per_page=100" \
        --jq '.[] | select(.event == "labeled" and .label.name == "lore-busy") | .created_at' 2>/dev/null | tail -n 1)
  [ -n "$at" ] || return 1
  python3 - "$at" <<'PY'
import datetime, sys
at = datetime.datetime.fromisoformat(sys.argv[1].strip().replace("Z", "+00:00"))
age = (datetime.datetime.now(datetime.timezone.utc) - at).total_seconds()
sys.exit(0 if age < 2 * 3600 else 1)
PY
}

done_ok() {      # Claude was called, or already has the issue
  [ -n "$FACTS" ] && say "$FACTS${PROMISE:+ $PROMISE}"
  rm -f "$OUT"; exit 0
}

done_waiting() { # nobody was woken: say so on the issue
  if [ -n "$FACTS" ]; then say "$FACTS $HINT"; else say "🤖 $HINT"; fi
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '\n### Chưa gọi được Claude\n%s\n' "$1" >> "$GITHUB_STEP_SUMMARY"
  fi
  rm -f "$OUT"; exit 0
}

if fresh_busy; then
  echo "wake: phiếu $N đang có nhãn lore-busy (dưới 2 giờ) — Claude đang làm phiếu này, không gọi thêm."
  done_ok
fi

[ -n "${CLAUDE_TASK_URL:-}" ] && [ -n "${CLAUDE_TASK_TOKEN:-}" ] || {
  echo "::warning::Chưa cài CLAUDE_TASK_URL/CLAUDE_TASK_TOKEN: chưa gọi được Claude. Phiếu chờ đến khi thêm hai secret này rồi bấm Gọi Claude ngay, hoặc làm trong chat."
  done_waiting 'Thêm secrets `CLAUDE_TASK_URL` và `CLAUDE_TASK_TOKEN` (API trigger của tác vụ Claude cho repo này) để Claude bắt đầu ngay khi có việc. Không có lượt chạy mỗi giờ: hiện phiếu chờ đến khi bấm **Gọi Claude ngay** hoặc làm trong chat.'
}

BODY=$(printf '%s' "$WHY" | python3 -c 'import json,sys;print(json.dumps({"text":sys.stdin.read()[:300]}))')
CODE=000
for TRY in 1 2 3; do
  CODE=$(curl -s -o "$OUT" -w '%{http_code}' --max-time 30 -X POST "$CLAUDE_TASK_URL" \
    -H "Authorization: Bearer $CLAUDE_TASK_TOKEN" \
    -H "anthropic-beta: experimental-cc-routine-2026-04-01" -H "anthropic-version: 2023-06-01" \
    -H "Content-Type: application/json" -d "$BODY") || true
  case "$CODE" in
    2*) echo "wake: Claude đã được gọi ($(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('claude_code_session_url',''))" "$OUT" 2>/dev/null))"
        done_ok ;;
    000|429|5*) echo "wake: lần $TRY không được (HTTP $CODE)"
        [ "$TRY" -lt 3 ] && sleep $((BACKOFF * TRY)) ;;
    *)  break ;;                      # 401, 403, 404…: trying again changes nothing
  esac
done
echo "::warning::wake: gọi Claude không được (HTTP $CODE) — bấm Gọi Claude ngay sau, hoặc làm trong chat"
head -c 300 "$OUT" 2>/dev/null; echo
done_waiting "Gọi Claude không được (HTTP $CODE). Bấm **Gọi Claude ngay** để thử lại; nếu vẫn lỗi, kiểm tra hai secret \`CLAUDE_TASK_URL\` và \`CLAUDE_TASK_TOKEN\`."
