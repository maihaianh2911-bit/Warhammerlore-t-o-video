"""Every shot of picks.json at each keyframe of its camera move (start, via…, END), framed exactly as the video frames it.

Usage: python3 -m factory.preview --job lore/<N> --images <img folder> --voice <voice folder> --out preview.jpg
Also writes the list of edits next to the sheet (<out>.md: shot, line, picture, edit, why), the same table the
render publishes as edits.md.
"""
import argparse
import json
from pathlib import Path

from .art import contact_sheet, grade_frame
from .render import SIZES, load_images, shot_picture, shot_views
from .edits import edits_table
from .script import faster, line_times, load_job, load_picks, load_style, script_lines, shot_frames


def shot_seconds(job, shots, voice=None, tempo=1.0):
    """Length of every shot: from the voice timing when there is one, else about 15 characters a second."""
    if voice and (voice / "timing.json").is_file():
        timing = json.loads((voice / "timing.json").read_text(encoding="utf-8"))
        if timing.get("text") == job.text:
            duration, starts, ends = faster(timing, tempo)
            frames = round(duration * 30)
            ranges = shot_frames(shots, line_times(job.spans, starts, ends), frames, 30)
            return [(last - first) / 30 for first, last in ranges]
    starts = [job.spans[int(shot.get("at", 1)) - 1][0] for shot in shots] + [len(job.text)]
    return [max(1.0, (after - before) / 15 / tempo) for before, after in zip(starts, starts[1:])]


def preview(job_dir, images_dir, out, voice=None):
    job = load_job(job_dir / "script.json")
    images, shots = load_picks(job_dir / "picks.json", len(job.spans))
    pictures = load_images(images, job_dir, images_dir)
    size = SIZES["preview"]
    seconds = shot_seconds(job, shots, voice, load_style(job_dir / "picks.json")["tempo"])
    tiles = []
    for index, shot in enumerate(shots):
        picture, plan = shot_picture(shot, index, images, pictures, size, seconds[index])
        name = shot.get("img") or shot["theme"]
        views = shot_views(grade_frame(picture), plan, size)
        for step, view in enumerate(views):
            label = "start" if step == 0 else "END" if step == len(views) - 1 else f"via{step}"
            text = f"{index + 1} L{shot.get('at', 1)} {seconds[index]:.0f}s {name} {label}"
            if "edit" in shot and step == 0:      # the first tile of a shot names its edit, the others its picture
                text = f"{index + 1} L{shot.get('at', 1)} {seconds[index]:.0f}s [{shot['edit']}]"
            tiles.append((view.resize((216, 384)), text[:34]))
    contact_sheet(tiles, out, columns=6)
    Path(out).with_suffix(".md").write_text(edits_table(shots, script_lines(job), seconds), encoding="utf-8")
    return len(shots)


def main():
    parser = argparse.ArgumentParser(description="Xem trước khung hình của từng cảnh.")
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--voice", type=Path, help="thư mục voice/ của phiếu, để biết đúng độ dài từng cảnh")
    args = parser.parse_args()
    try:
        count = preview(args.job, args.images, args.out, args.voice)
    except (OSError, KeyError, ValueError) as error:
        parser.exit(1, f"Không xem trước được: {error}\n")
    print(f"{args.out}: {count} cảnh; cách edit từng cảnh: {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
