"""Machine steps of one video on GitHub Actions. Usage: python3 -m factory.run <N> <step> [<step> ...]

  prepare  voice (VN11, one take; reused when the script did not change), voice check (Whisper), pictures the
           owner attached to the issue, Wikimedia Commons search for script.json "queries"
           → renders/lore/<N>/voice/, img/issue/, img/1/
  search   every lore/<N>/search-<r>.json whose round is not on renders yet → renders/lore/<N>/img/<r>/
  render   video from script.json + picks.json → renders/lore/<N>/video.mp4, subtitles.srt, credits.md, sheet.jpg
After prepare the issue waits for Claude (lore-pick) unless picks.json exists, then render runs too.
`python3 -m factory.run todo` reads changed file names on stdin and prints "<N> <steps>" lines.
Needs GH_TOKEN, GITHUB_REPOSITORY; prepare needs VN11_API_KEY.
"""
import json
import os
import re
import shutil
import subprocess
import sys
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


class Run:
    def __init__(self, number):
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
        for label in remove:
            self.gh("issue", "edit", self.n, "--remove-label", label)
        if add:
            self.gh("issue", "edit", self.n, "--add-label", ",".join(add))

    def comment(self, body):
        self.gh("issue", "comment", self.n, "--body", body)

    def wake(self, why):
        subprocess.run(["bash", str(ROOT / "scripts" / "wake_claude.sh"), why])

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
        """Copy work-relative files or folders to renders/lore/<N>/ in one commit."""
        tree = ROOT / "out" / "renders-wt"
        shutil.rmtree(tree, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=ROOT)
        fetch = ["git", "fetch", "-q", "--depth", "1", self.url, "+refs/heads/renders:refs/remotes/origin/renders"]
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
        subprocess.run(["git", *BOT, "commit", "-q", "-m", f"lore/{self.n}: {message}"], cwd=tree)
        for _ in range(4):
            if subprocess.run(["git", "push", "-q", self.url, "HEAD:renders"], cwd=tree).returncode == 0:
                print(f"published lore/{self.n}: {message}")
                return
            subprocess.run(["git", "fetch", "-q", "--depth", "1", self.url, "renders"], cwd=tree)
            subprocess.run(["git", *BOT, "rebase", "-q", "FETCH_HEAD"], cwd=tree)
        raise SystemExit("không đẩy được lên nhánh renders")

    def commons(self, folder, queries, earlier=()):
        """One search round; skipped when the same queries were already searched."""
        marker = folder / "queries.json"
        if marker.is_file() and json.loads(marker.read_text(encoding="utf-8")) == queries:
            return False
        shutil.rmtree(folder, ignore_errors=True)
        seen = ":".join(str(path) for path in earlier)
        self.module("commons", folder, *queries, env={**os.environ, "FIND_SEEN": seen})
        marker.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
        return True

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

    def prepare(self):
        from .script import load_job

        job = load_job(self.job / "script.json")
        self.labels(add=["lore-voice"], remove=["lore-plan", "lore-failed"])
        voice = self.work / "voice"
        self.module("narrate", "--job", self.job, "--out", voice, "--previous", voice)
        paths = ["voice"]
        attached, changed = self.attachments()
        if changed:
            paths.append("img/issue")
        if job.queries and self.commons(self.work / "img" / "1", list(job.queries)):
            paths.append("img/1")
        self.publish(paths, "giọng đọc + ảnh")
        return json.loads((voice / "timing.json").read_text(encoding="utf-8")), attached

    def search(self):
        done = []
        for path in sorted(self.job.glob("search-*.json")):
            round_name = path.stem[len("search-"):]
            queries = json.loads(path.read_text(encoding="utf-8"))["queries"]
            images = self.work / "img"
            earlier = [folder for folder in sorted(images.iterdir()) if folder.name not in (round_name, "issue")] \
                if images.is_dir() else []
            if self.commons(images / round_name, queries, earlier):
                done.append(f"img/{round_name}")
        _, changed = self.attachments()   # pictures the owner attached since the last step
        if changed:
            done.append("img/issue")
        if done:
            self.publish(done, "tìm thêm ảnh")

    def render(self):
        self.labels(add=["lore-render"], remove=["lore-pick", "lore-check", "lore-done", "lore-fix", "lore-failed"])
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
        print("\n".join(todo(sys.stdin.read().split())))
        return
    number, steps = sys.argv[1], sys.argv[2:]
    if not number.isdigit() or not steps or any(step not in ORDER for step in steps):
        raise SystemExit(__doc__)
    run = Run(number)
    run.fetch_renders()
    has_picks = (run.job / "picks.json").is_file()
    if "prepare" in steps:
        timing, attached = run.prepare()
        if not has_picks:
            review = len(timing["review"])
            run.labels(add=["lore-pick"], remove=["lore-voice"])
            run.comment(
                f"🤖 Giọng đọc xong: {len(timing['lines'])} câu, {timing['duration']:.0f} giây"
                f"{f' ({review} đoạn cần Claude nghe lại)' if review else ''}. "
                f"{f'Đã lấy {attached} ảnh đính kèm trong phiếu. ' if attached else ''}"
                "Claude sẽ chọn hình cho từng ý."
            )
            run.wake(f"Phiếu 40K số {number}: giọng và ảnh đã sẵn sàng, chờ chọn hình.")
        elif "render" not in steps:
            steps.append("render")
    if "search" in steps:
        run.search()
        if "render" not in steps:
            run.labels(add=["lore-pick"], remove=["lore-voice"])
    if "render" in steps:
        if not (run.work / "voice" / "timing.json").is_file():
            raise SystemExit("chưa có giọng đọc cho phiếu này (cần script.json)")
        if not has_picks:
            raise SystemExit("chưa có picks.json cho phiếu này")
        minutes, seconds = divmod(round(run.render()), 60)
        run.labels(add=["lore-check"], remove=["lore-render", "lore-voice"])
        run.comment(
            f"🤖 Đã dựng xong bản video ({minutes} phút {seconds:02d} giây). "
            "Claude đang kiểm tra lại từng cảnh trước khi giao.\n\n"
            f"- Video: {run.link('video.mp4')}\n- Ảnh các cảnh: {run.link('sheet.jpg')}"
        )
        run.wake(f"Phiếu 40K số {number}: video đã dựng, chờ kiểm tra.")


if __name__ == "__main__":
    main()
