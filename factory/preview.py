"""Every shot of picks.json at the start and at the end of its camera move, framed exactly as the video frames it.

Usage: python3 -m factory.preview --job lore/<N> --images <img folder> --out preview.jpg
"""
import argparse
from pathlib import Path

from .art import contact_sheet, grade_frame
from .render import SIZES, load_images, shot_picture, shot_views
from .script import load_job, load_picks


def preview(job_dir, images_dir, out):
    job = load_job(job_dir / "script.json")
    images, shots = load_picks(job_dir / "picks.json", len(job.spans))
    pictures = load_images(images, job_dir, images_dir)
    size = SIZES["preview"]
    tiles = []
    for index, shot in enumerate(shots):
        picture, move = shot_picture(shot, index, images, pictures, size)
        name = shot.get("img") or "+".join(shot.get("collage", [])) or shot["theme"]
        for label, view in zip(("start", "end"), shot_views(grade_frame(picture), move, size)):
            tiles.append((view.resize((216, 384)), f"{index + 1} L{shot.get('at', 1)} {name} {label}"[:34]))
    contact_sheet(tiles, out, columns=6)
    return len(shots)


def main():
    parser = argparse.ArgumentParser(description="Xem trước khung hình của từng cảnh.")
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        count = preview(args.job, args.images, args.out)
    except (OSError, KeyError, ValueError) as error:
        parser.exit(1, f"Không xem trước được: {error}\n")
    print(f"{args.out}: {count} cảnh")


if __name__ == "__main__":
    main()
