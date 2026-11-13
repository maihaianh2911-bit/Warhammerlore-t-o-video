# Warhammerlore-t-o-video — notes for Claude

Read `AGENT.md` (how a video is made, the owner's standing decisions). The owner is Vietnamese and not technical:
answer in short, simple Vietnamese, no jargon.

This repo makes one thing: vertical Warhammer 40K lore shorts in German — the saved `ww40k` voice, pictures
chosen for each idea, subtitles timed to the voice. One issue `[40K] …` = one video; the machine steps run on
GitHub Actions (`lore.yml` → `factory/run.py`), Claude's steps are in `AGENT.md`. Unattended, those steps are done
by the owner's Claude task "japan-video-factory", which also checks `lore-*` issues of this repo (see
`maihaianh2911-bit/japan-video-factory` → `AGENT_NIGHTLY.md`). There is no hourly run (owner, 13/11/2026): the task
starts only when GitHub calls it, which needs the secrets `CLAUDE_TASK_URL` and `CLAUDE_TASK_TOKEN` in this repo
(the same values as in japan-video-factory). Without them, or when a call is missed, the issue waits for the
button "Gọi Claude ngay" or a chat.
An issue opened before the workflow existed (or reopened) gets no labels by itself: add `lore` and `lore-plan`.

## When the owner pastes a script in a chat
1. Create one issue in this repo: title `[40K] <tên video>`, body = the script exactly as pasted under
   `### Kịch bản (bắt buộc)`. No labels: the workflow adds them.
2. Do Claude's steps of `AGENT.md` for that issue right away (claim with `lore-busy` as written there).
3. Give the owner the links to the video, the subtitles and the picture credits.

## Changing the pipeline
Before pushing to `main`: `python3 -m unittest discover -s tests`, `python3 tests/smoke.py`,
`python3 -m compileall -q factory tests`. Never touch secrets. Comments posted on GitHub start with 🤖 (they come
from the owner's account). No pull requests unless asked.
