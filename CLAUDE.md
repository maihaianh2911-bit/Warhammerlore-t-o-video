# Warhammerlore-t-o-video — notes for Claude

## Iron rules (owner, 16/11/2026) — they come before everything else in this file
1. **The video is in the channel's language: German (tiếng Đức).** The voice is the saved German `ww40k` voice, and the script lines, subtitles and
   on-screen text are in German (tiếng Đức). A script that arrives in another language is translated faithfully into German (tiếng Đức)
   first. Never a voice or text of another language: check the language of `lines` and the voice before the voice
   step, and again on the finished video. A video in the wrong language is not delivered: fix it and render again.
2. **No video under 60 seconds.** Before the voice step, estimate the length from the script (use the seconds per
   line of this channel's earlier videos); after the voice step, read the real length of the speech (the machine
   comment gives it). If the video would be under 60 seconds, **write the script longer** (more true facts and
   detail on the same subject, in the owner's tone, nothing invented) until it passes 60 seconds, tell the owner on
   the issue what was added, and only then go on. This is the one exception to "never change the owner's script".
   Never render or deliver a video under 60 seconds. Only exception: a trial or sample video — the owner says so,
   or the issue title or notes say `thử`, `mẫu`, `test` or `demo`.

Read `AGENT.md` (how a video is made, the owner's standing decisions). The owner is Vietnamese and not technical:
answer in short, simple Vietnamese, no jargon.

This repo makes one thing: vertical Warhammer 40K lore shorts in German — the saved `ww40k` voice, pictures
chosen for each idea, subtitles timed to the voice. One issue `[40K] …` = one video; the machine steps run on
GitHub Actions (`lore.yml` → `factory/run.py`), Claude's steps are in `AGENT.md`. Unattended, those steps are done
by the owner's Claude task "japan-video-factory", which also checks `lore-*` issues of this repo (see
`maihaianh2911-bit/japan-video-factory` → `AGENT_NIGHTLY.md`), or by this repo's own task when each repo has its
own Claude seat (its prompt: "Làm theo AGENT.md của repo maihaianh2911-bit/Warhammerlore-t-o-video."). There is no hourly run (owner, 13/11/2026): the task
starts only when GitHub calls it, which needs the secrets `CLAUDE_TASK_URL` and `CLAUDE_TASK_TOKEN` in this repo
(the same values as in japan-video-factory). Without them, or when a call is missed, the issue waits for the
button "Gọi Claude ngay" or a chat.
An issue opened before the workflow existed (or reopened) gets no labels by itself: add `lore` and `lore-plan`.

## When you were started by GitHub (a Claude task, nobody in the chat)
The prompt may be as short as "Làm việc đang chờ trong repo này" ("do the work waiting in this repo"), and GitHub
adds a line such as "Phiếu 40K số 1: giọng và ảnh đã sẵn sàng, chờ chọn hình". Then: follow `AGENT.md` from §0 (its first check lists the `lore-*` issues waiting for you). Nobody answers questions, so do not ask; comments go on the issues
(🤖, Vietnamese).

## When the owner pastes a script in a chat
1. Create one issue in this repo: title `[40K] <tên video>`, body = the script exactly as pasted under
   `### Kịch bản (bắt buộc)`. No labels: the workflow adds them.
2. Add `lore-busy` to the issue right away, then do Claude's steps of `AGENT.md` for it (claim as written there,
   "In a chat").
3. Send the finished video itself into the chat as a file (owner, 16/11/2026: "gửi thẳng video lên đây, đừng gửi
   link"), with `subtitles.srt`, `caption.txt` (the posting caption, owner 16/11/2026) and `credits.md` attached
   as files too; no links in the chat. (The issue's closing 🤖 comment links video, subtitles, caption and credits.)

## Changing the pipeline
Before pushing to `main`: `python3 -m unittest discover -s tests`, `python3 tests/smoke.py`,
`python3 -m compileall -q factory tests`. Never touch secrets. Comments posted on GitHub start with 🤖 (they come
from the owner's account). No pull requests unless asked.
