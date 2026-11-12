# Warhammerlore-t-o-video — notes for Claude

Read `AGENT.md` (how a video is made, the owner's standing decisions). The owner is Vietnamese and not technical:
answer in short, simple Vietnamese, no jargon.

This repo makes one thing: vertical Warhammer 40K lore shorts in German — the saved `ww40k` voice, pictures
chosen for each idea, subtitles timed to the voice. One issue `[40K] …` = one video; the machine steps run on
GitHub Actions (`lore.yml` → `factory/run.py`), Claude's steps are in `AGENT.md`. A Claude routine does those
steps unattended when GitHub calls it, so a video also gets made when nobody is in a chat.

## When the owner pastes a script in a chat
1. Create one issue in this repo: title `[40K] <tên video>`, body = the script exactly as pasted under
   `### Kịch bản (bắt buộc)`. No labels: the workflow adds them.
2. Do Claude's steps of `AGENT.md` for that issue right away (claim with `lore-busy` as written there).
3. Give the owner the links to the video, the subtitles and the picture credits.

## Changing the pipeline
Before pushing to `main`: `python3 -m unittest discover -s tests`, `python3 tests/smoke.py`,
`python3 -m compileall -q factory tests`. Never touch secrets. Comments posted on GitHub start with 🤖 (they come
from the owner's account). No pull requests unless asked.
