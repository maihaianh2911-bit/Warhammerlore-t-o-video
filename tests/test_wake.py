"""scripts/wake_claude.sh with a fake curl and a fake gh: retries, the busy claim, and the comment on the issue."""
import datetime
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wake_claude.sh"

CURL = """#!/usr/bin/env bash
# answers with the next HTTP code of FAKE_CODES
count=$(cat "$FAKE_DIR/calls" 2>/dev/null || echo 0)
echo $((count + 1)) > "$FAKE_DIR/calls"
set -- $FAKE_CODES
shift "$count" 2>/dev/null
code=${1:-000}
printf '%s' "$code"
"""

GH = """#!/usr/bin/env bash
case "$*" in
  *"-X POST"*comments*) for word in "$@"; do case "$word" in body=*) printf '%s\\n---\\n' "${word#body=}" >> "$FAKE_DIR/comments";; esac; done ;;
  *events*) [ -n "$FAKE_BUSY_AT" ] && echo "$FAKE_BUSY_AT" ;;
  *) printf '%s\\n' $FAKE_LABELS ;;
esac
exit 0
"""


def stamp(hours_ago):
    at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


class WakeTest(unittest.TestCase):
    def wake(self, *arguments, codes="200", secrets=True, labels="lore lore-pick", busy_at=""):
        folder = Path(tempfile.mkdtemp())
        for name, text in (("curl", CURL), ("gh", GH)):
            (folder / name).write_text(text, encoding="utf-8")
            (folder / name).chmod(stat.S_IRWXU)
        env = {"PATH": f"{folder}:{os.environ['PATH']}", "FAKE_DIR": str(folder), "FAKE_CODES": codes,
               "FAKE_LABELS": labels, "FAKE_BUSY_AT": busy_at, "WAKE_BACKOFF": "0",
               "GH_TOKEN": "t", "GITHUB_REPOSITORY": "owner/repo"}
        if secrets:
            env.update(CLAUDE_TASK_URL="https://example.invalid/fire", CLAUDE_TASK_TOKEN="x")
        result = subprocess.run(["bash", str(SCRIPT), *arguments], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)      # a wake never fails the workflow
        calls = int((folder / "calls").read_text()) if (folder / "calls").exists() else 0
        comments = (folder / "comments").read_text(encoding="utf-8") if (folder / "comments").exists() else ""
        return calls, comments

    def test_a_call_that_works_posts_the_facts_and_the_promise(self):
        calls, comments = self.wake("vì sao", "7", "🤖 Giọng đọc xong.", "Claude sẽ chọn hình.")
        self.assertEqual(calls, 1)
        self.assertIn("🤖 Giọng đọc xong. Claude sẽ chọn hình.", comments)

    def test_a_busy_server_is_tried_three_times(self):
        calls, comments = self.wake("vì sao", "7", "🤖 Xong.", "Claude sẽ làm.", codes="503 000 200")
        self.assertEqual(calls, 3)
        self.assertIn("Claude sẽ làm.", comments)

    def test_a_failed_call_never_promises_and_names_the_button(self):
        calls, comments = self.wake("vì sao", "7", "🤖 Giọng đọc xong.", "Claude sẽ chọn hình.", codes="503 503 503")
        self.assertEqual(calls, 3)
        self.assertIn("🤖 Giọng đọc xong.", comments)
        self.assertNotIn("Claude sẽ chọn hình.", comments)
        self.assertIn("Chưa gọi được Claude", comments)
        self.assertIn("https://github.com/owner/repo/actions/workflows/wake.yml", comments)

    def test_a_refused_key_is_not_tried_again(self):
        calls, comments = self.wake("vì sao", "7", codes="401 200")
        self.assertEqual(calls, 1)
        self.assertTrue(comments.startswith("🤖 Chưa gọi được Claude"))

    def test_missing_secrets_are_reported_on_the_issue(self):
        calls, comments = self.wake("vì sao", "7", "🤖 Đã nhận kịch bản.", "Claude bắt đầu ngay.", secrets=False)
        self.assertEqual(calls, 0)
        self.assertIn("Chưa gọi được Claude", comments)
        self.assertNotIn("Claude bắt đầu ngay.", comments)

    def test_a_fresh_claim_is_left_alone(self):
        calls, comments = self.wake("vì sao", "7", "🤖 Giọng đọc xong.", "Claude sẽ chọn hình.", codes="503",
                                    labels="lore lore-pick lore-busy", busy_at=stamp(0.5))
        self.assertEqual(calls, 0)                                  # Claude already has the issue: no second call
        self.assertNotIn("Chưa gọi được Claude", comments)
        self.assertIn("🤖 Giọng đọc xong. Claude sẽ chọn hình.", comments)

    def test_a_stale_claim_does_not_stop_the_call(self):
        calls, _ = self.wake("vì sao", "7", labels="lore lore-pick lore-busy", busy_at=stamp(3))
        self.assertEqual(calls, 1)

    def test_the_button_has_no_issue_and_writes_no_comment(self):
        calls, comments = self.wake("chủ kênh bấm nút", codes="500 500 500")
        self.assertEqual((calls, comments), (3, ""))


if __name__ == "__main__":
    unittest.main()
