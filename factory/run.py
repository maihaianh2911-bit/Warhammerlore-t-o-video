"""Machine steps of one video on GitHub Actions. Usage: python3 -m factory.run <N> <step> [<step> ...]

  prepare  voice (VN11, one take; reused when the script did not change), voice check (Whisper), pictures the
           owner attached to the issue, picture search for script.json "queries" (40K Gallery catalogue,
           ArtStation, Warhammer 40k Wiki, Wikimedia Commons)
           → renders/lore/<N>/voice/, img/issue/, img/1/
  search   every lore/<N>/search-<r>.json whose round is not on renders yet → renders/lore/<N>/img/<r>/
  render   video from script.json + picks.json → renders/lore/<N>/video.mp4, subtitles.srt, credits.md, sheet.jpg
After prepare the issue waits for Claude (lore-pick) unless picks.json exists, then render runs too.
`python3 -m factory.run todo` reads changed file names on stdin and prints "<N> <steps>" lines;
`python3 -m factory.run matrix` turns those lines into the JSON list of the workflow's job matrix;
`python3 -m factory.run mark <N> <step> ...` only moves the issue's step label (run at once, before the work job).
Needs GH_TOKEN, GITHUB_REPOSITORY; prepare needs VN11_API_KEY.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["prepare", "search", "render"]
BOT = ["-c", "user.name=render-bot", "-c", "user.email=render-bot@users.noreply.github.com"]


def todo(files):
    """Steps to run for the lore/<N>/ files changed by a push."""
    jobs = {}
    for name in files:
        match = re.match(r"lore/(\d+)/(.+)$", name)
        if not match:
            continue
        number, rest = match.groups()
        step = ("prepare" if rest == "script.json" else "search" if re.fullmatch(r"search-\w+\.json", rest)
                else "render" if rest == "picks.json" or rest.startswith("own/") else None)
        if step and step not in jobs.setdefault(number, []):
            jobs[number].append(step)
    return [f"{number} {' '.join(sorted(steps, key=ORDER.index))}" for number, steps in jobs.items() if steps]


def matrix(lines):
    """"<N> <steps>" lines → [{"n": "<N>", "steps": "<steps>"}], one workflow job per issue."""
    jobs = [line.split() for line in lines if line.split()]
    return [{"n": words[0], "steps": " ".join(words[1:])} for words in jobs
            if words[0].isdigit() and words[1:] and all(step in ORDER for step in words[1:])]


def catch_up(job, work, steps):
    """Steps a run must also do because the run that should have done them never started.

    Runs of one issue wait for each other, and GitHub keeps only the newest waiting run: when Claude pushes a
    fixed script, then a search round, then the picks while a step is still running, only the last push runs.
    So a push run also reads the voice when the script on main is not the one that was read, and searches every
    round that has no result yet. Both are skipped by the steps themselves when there is nothing to do.
    """
    steps = list(steps)
    timing = work / "voice" / "timing.json"
    if "prepare" not in steps and (job / "script.json").is_file():
        try:
            from .script import load_job
            text = load_job(job / "script.json").text
            read = json.loads(timing.read_text(encoding="utf-8")).get("text") if timing.is_file() else None
            if read != text:
                steps.append("prepare")
        except (OSError, ValueError):
            pass    # a broken script.json is reported by the step that needs it
    if "search" not in steps and any(
            not (work / "img" / path.stem[len("search-"):] / "index.json").is_file()
            for path in job.glob("search-*.json")):
        steps.append("search")
    return sorted(steps, key=ORDER.index)


def failed_queries(index, queries):
    """Queries of a search round whose search failed (index.json entries with "error"); [] when the index is not
    of these queries."""
    try:
        entries = json.loads(Path(index).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if [entry.get("query") for entry in entries] != list(queries):
        return []
    return [entry["query"] for entry in entries if entry.get("error")]


def search_note(failed):
    """What the issue comment says about the picture search."""
    if not failed:
        return "Hình đã tìm xong."
    names = ", ".join(failed[:6]) + ("…" if len(failed) > 6 else "")
    return (f"Tìm hình chưa xong: {len(failed)} từ khóa bị lỗi mạng ({names}). "
            "Các từ khóa này sẽ được tìm lại khi chạy lại bước prepare hoặc search.")


class Run:
    def __init__(self, number):
        self.failed = []    # picture searches of this run that failed (a site was down): tried again next run
        self.n = number
        self.job = ROOT / "lore" / number
        self.work = ROOT / "out" / f"lore-{number}"          # mirror of renders/lore/<N>/ for this run
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.url = f"https://x-access-token:{os.environ['GH_TOKEN']}@github.com/{self.repo}.git"

    def sh(self, *command, **options):
        return subprocess.run(command, check=True, cwd=options.pop("cwd", ROOT), **options)

    def module(self, name, *arguments, **options):
        return self.sh(sys.executable, "-m", f"factory.{name}", *map(str, arguments), **options)

    def gh(self, *arguments):
        return subprocess.run(["gh", *arguments], check=False, capture_output=True, text=True)

    def labels(self, add=(), remove=()):
        """New labels first, then the old ones go: an API error never leaves the issue without a step label."""
        if add:
            self.gh_retry("issue", "edit", self.n, "--add-label", ",".join(add))
        for label in remove:
            if label not in add:
                self.gh_retry("issue", "edit", self.n, "--remove-label", label)

    def gh_retry(self, *arguments):
        for attempt in range(2):
            result = self.gh(*arguments)
            if result.returncode == 0:
                return result
            print(f"gh {' '.join(arguments)}: {result.stderr.strip()[:300]}", flush=True)
        return result

    def comment(self, body):
        self.gh("issue", "comment", self.n, "--body", body)

    def wake(self, why, facts="", promise=""):
        """Call Claude, then post `facts` on the issue as one comment. `promise` (what Claude does next) is added
        only when Claude was called or already holds the issue; otherwise the script writes that Claude could not
        be called and which button to press (scripts/wake_claude.sh)."""
        subprocess.run(["bash", str(ROOT / "scripts" / "wake_claude.sh"), why, self.n, facts, promise])

    def link(self, path):
        return f"https://github.com/{self.repo}/blob/renders/lore/{self.n}/{path}"

    def fetch_renders(self):
        """Current renders/lore/<N>/ → work folder (empty when nothing was published yet)."""
        self.work.mkdir(parents=True, exist_ok=True)
        fetch = ["git", "fetch", "-q", "--depth", "1", self.url, "+refs/heads/renders:refs/remotes/origin/renders"]
        if subprocess.run(fetch, cwd=ROOT).returncode:
            return
        listing = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/renders", f"lore/{self.n}/"],
                                 cwd=ROOT, capture_output=True, text=True).stdout
        if listing.strip():
            archive = subprocess.run(["git", "archive", "origin/renders", f"lore/{self.n}"],
                                     cwd=ROOT, capture_output=True, check=True).stdout
            scratch = ROOT / "out" / "renders-tmp"
            shutil.rmtree(scratch, ignore_errors=True)
            scratch.mkdir(parents=True)
            subprocess.run(["tar", "-x", "-C", str(scratch)], input=archive, check=True)
            shutil.copytree(scratch / "lore" / self.n, self.work, dirs_exist_ok=True)

    def publish(self, paths, message):
        """Copy work-relative files or folders to renders/lore/<N>/ in one commit.

        Every attempt starts from the freshly fetched tip of renders and copies the files in again, so a run that
        lost the race to another one never rebases (a shallow rebase can stop on a conflict and then push nothing).
        """
        tree = ROOT / "out" / "renders-wt"
        fetch = ["git", "fetch", "-q", "--depth", "1", self.url, "+refs/heads/renders:refs/remotes/origin/renders"]
        for attempt in range(5):
            if tree.exists():
                subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT)
                shutil.rmtree(tree, ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], cwd=ROOT)
            if subprocess.run(fetch, cwd=ROOT).returncode == 0:
                self.sh("git", "worktree", "add", "-q", "--detach", str(tree), "origin/renders")
            else:   # new repo: the renders branch does not exist yet → start it empty
                self.sh("git", "worktree", "add", "-q", "--detach", str(tree))
                self.sh("git", "checkout", "-q", "--orphan", "renders", cwd=tree)
                subprocess.run(["git", "rm", "-rf", "-q", "."], cwd=tree)
            for path in paths:
                source, target = self.work / path, tree / "lore" / self.n / path
                if source.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(source, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(source, target)
            self.sh("git", *BOT, "add", "-A", cwd=tree)
            if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=tree).returncode == 0:
                print(f"lore/{self.n}: {message} — không có gì mới để đăng")
                return
            self.sh("git", *BOT, "commit", "-q", "-m", f"lore/{self.n}: {message}", cwd=tree)
            if subprocess.run(["git", "push", "-q", self.url, "HEAD:renders"], cwd=tree).returncode == 0:
                print(f"published lore/{self.n}: {message}")
                return
            time.sleep(5 * (attempt + 1))
        raise SystemExit("không đẩy được lên nhánh renders")

    def find_images(self, folder, queries, earlier=()):
        """One search round. Returns None when the same queries were already searched, "new" for a fresh round
        (every number may mean another picture), "retried" when only the queries that failed last time were
        searched again (the other pictures keep their numbers).

        The done-marker queries.json is written only when no query failed, so the next prepare/search run tries
        the failed ones again; they are listed in self.failed for the comment on the issue.
        """
        marker = folder / "queries.json"
        if marker.is_file() and json.loads(marker.read_text(encoding="utf-8")) == queries:
            return None
        index = folder / "index.json"
        kind = "retried" if failed_queries(index, queries) else "new"
        if kind == "new":
            shutil.rmtree(folder, ignore_errors=True)
        seen = ":".join(str(path) for path in earlier)
        self.module("find_images", folder, *queries, env={**os.environ, "FIND_SEEN": seen})
        failed = failed_queries(index, queries)
        if failed:
            self.failed += failed
        else:
            marker.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
        return kind

    def attachments(self):
        from .attachments import attachment_urls, download, owner_texts

        issue = self.gh("api", f"repos/{self.repo}/issues/{self.n}")
        comments = self.gh("api", f"repos/{self.repo}/issues/{self.n}/comments?per_page=100")
        if issue.returncode or comments.returncode:
            raise SystemExit("không đọc được phiếu để lấy ảnh đính kèm")
        owner = self.repo.split("/")[0]
        urls = attachment_urls(owner_texts(json.loads(issue.stdout), json.loads(comments.stdout), owner))
        folder = self.work / "img" / "issue"
        marker = folder / "urls.json"
        if not urls or (marker.is_file() and json.loads(marker.read_text(encoding="utf-8")) == urls):
            return 0, False
        shutil.rmtree(folder, ignore_errors=True)
        count = download(urls, folder)
        marker.write_text(json.dumps(urls), encoding="utf-8")
        return count, True

    def mark(self, steps):
        """The label of the step that is about to run, set as soon as the push is seen: the work job itself may
        wait for an earlier run of this issue and needs ~40 s for its tools."""
        if "prepare" in steps:
            self.voice_labels()
        elif "render" in steps and (self.job / "picks.json").is_file():
            self.render_labels()

    def voice_labels(self):
        self.labels(add=["lore-voice"], remove=["lore-plan", "lore-failed"])

    def render_labels(self):
        self.labels(add=["lore-render"], remove=["lore-pick", "lore-check", "lore-done", "lore-fix", "lore-failed"])

    def prepare(self):
        from .script import load_job

        job = load_job(self.job / "script.json")
        self.voice_labels()
        voice = self.work / "voice"
        self.module("narrate", "--job", self.job, "--out", voice, "--previous", voice)
        self.publish(["voice"], "giọng đọc")   # saved first: a failed picture search must not cost a second reading
        paths = []
        attached, changed = self.attachments()
        if changed:
            paths.append("img/issue")
        searched = self.find_images(self.work / "img" / "1", list(job.queries)) if job.queries else None
        if searched:
            paths.append("img/1")
        if paths:
            self.publish(paths, "ảnh")
        # only a fresh round changes what 1/k-n.jpg means; a retry of failed queries keeps the other numbers
        return json.loads((voice / "timing.json").read_text(encoding="utf-8")), attached, searched == "new"

    def search(self):
        done = []
        for path in sorted(self.job.glob("search-*.json")):
            round_name = path.stem[len("search-"):]
            queries = json.loads(path.read_text(encoding="utf-8"))["queries"]
            images = self.work / "img"
            earlier = [folder for folder in sorted(images.iterdir()) if folder.name not in (round_name, "issue")] \
                if images.is_dir() else []
            if self.find_images(images / round_name, queries, earlier):
                done.append(f"img/{round_name}")
        _, changed = self.attachments()   # pictures the owner attached since the last step
        if changed:
            done.append("img/issue")
        if done:
            self.publish(done, "tìm thêm ảnh")

    def render(self):
        self.render_labels()
        out = ROOT / "out" / f"render-{self.n}"
        shutil.rmtree(out, ignore_errors=True)
        self.module("render", "--job", self.job, "--voice", self.work / "voice",
                    "--images", self.work / "img", "--out", out)
        names = ["video.mp4", "sheet.jpg", "cover.jpg", "subtitles.srt", "credits.md", "scenes.json"]
        for name in names:
            shutil.copy(out / name, self.work / name)
        if (self.work / "video.mp4").stat().st_size > 95 * 1024 * 1024:
            raise SystemExit("video.mp4 lớn hơn 95 MB, không đưa lên nhánh renders được")
        self.publish(names, "video")
        return json.loads((out / "scenes.json").read_text(encoding="utf-8"))["duration"]


def main():
    if sys.argv[1:] == ["todo"]:
        print("\n".join(todo(line.strip() for line in sys.stdin.read().splitlines() if line.strip())))
        return
    if sys.argv[1:] == ["matrix"]:
        print(json.dumps(matrix(sys.stdin.read().splitlines())))
        return
    only_mark = sys.argv[1:2] == ["mark"]
    number, steps = (sys.argv[2:3] or [""])[0] if only_mark else sys.argv[1], sys.argv[3 if only_mark else 2:]
    if not number.isdigit() or not steps or any(step not in ORDER for step in steps):
        raise SystemExit(__doc__)
    run = Run(number)
    if only_mark:
        run.mark(steps)
        return
    run.fetch_renders()
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        steps = catch_up(run.job, run.work, steps)
    has_picks = (run.job / "picks.json").is_file()
    # one call to Claude, and one comment, once the pictures of this run are all there (prepare and search together)
    why = facts = promise = ""
    pictures = False    # the comment says how the picture search went
    if "prepare" in steps:
        timing, attached, searched = run.prepare()
        if has_picks and searched:
            # round 1 was searched again: its numbers (1/k-n.jpg) now mean other pictures, so picks.json is stale
            run.labels(add=["lore-pick"], remove=["lore-voice"])
            why = f"Phiếu 40K số {number}: tìm lại hình, cần chọn lại hình."
            facts = "🤖 Từ khóa tìm hình đã đổi nên bộ hình cũng đổi. Hình phải được chọn lại trước khi dựng."
            promise = "Claude sẽ chọn lại hình."
            steps = [step for step in steps if step != "render"]
        elif not has_picks:
            review = len(timing["review"])
            run.labels(add=["lore-pick"], remove=["lore-voice"])
            steps = [step for step in steps if step != "render"]    # nothing to render before the picks
            why = f"Phiếu 40K số {number}: giọng và ảnh đã sẵn sàng, chờ chọn hình."
            facts = (f"🤖 Giọng đọc xong: {len(timing['lines'])} câu, {timing['duration']:.0f} giây"
                     f"{f' ({review} đoạn cần nghe lại)' if review else ''}."
                     f"{f' Đã lấy {attached} ảnh đính kèm trong phiếu.' if attached else ''}")
            promise, pictures = "Claude sẽ chọn hình cho từng ý.", True
        elif "render" not in steps:
            steps.append("render")
    if "search" in steps:
        run.search()
        if "render" not in steps:
            run.labels(add=["lore-pick"], remove=["lore-voice"])
            # as after every machine step: Claude may have stopped waiting for this round
            why = why or f"Phiếu 40K số {number}: đã tìm thêm hình, chờ chọn hình."
    failed = getattr(run, "failed", [])     # searches that failed in this run (a site was down)
    if why:
        if pictures or failed:
            facts = f"{facts or '🤖'} {search_note(failed)}"
            why += f" {len(failed)} từ khóa tìm hình bị lỗi (\"error\" trong index.json)." if failed else ""
        run.wake(why, facts, promise)
    if "render" in steps and not has_picks and "prepare" not in steps and os.environ.get("GITHUB_EVENT_NAME") == "push":
        # own/ pictures pushed before picks.json: nothing to render yet, and nothing failed
        print("chưa có picks.json — chưa dựng; ảnh riêng sẽ được dùng khi có picks.json")
        steps.remove("render")
    if "render" in steps:
        if not (run.work / "voice" / "timing.json").is_file():
            raise SystemExit("chưa có giọng đọc cho phiếu này (cần script.json)")
        if not has_picks:
            raise SystemExit("chưa có picks.json cho phiếu này")
        minutes, seconds = divmod(round(run.render()), 60)
        run.labels(add=["lore-check"], remove=["lore-render", "lore-voice"])
        run.wake(
            f"Phiếu 40K số {number}: video đã dựng, chờ kiểm tra.",
            f"🤖 Đã dựng xong bản video ({minutes} phút {seconds:02d} giây), chưa kiểm tra từng cảnh.\n\n"
            f"- Video: {run.link('video.mp4')}\n- Ảnh các cảnh: {run.link('sheet.jpg')}\n\n"
            f"{search_note(failed) if failed else ''}",
            "Claude sẽ kiểm tra lại từng cảnh trước khi giao.",
        )


if __name__ == "__main__":
    main()
