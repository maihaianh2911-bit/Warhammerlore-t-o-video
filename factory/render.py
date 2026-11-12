import argparse
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .art import ART_ROOT, atmosphere, contact_sheet, fit_picture, grade_frame, open_picture, opening_collage
from .script import (
    line_times, load_job, load_picks, make_cues, opening_frames, shot_frames, write_subtitles,
)
from .voice import audio_duration


FPS = 30
SIZES = {"preview": (720, 1280), "full": (1080, 1920)}
CAMERA_MOVES = (
    ((1.06, 0.12, 0.36), (1.19, 0.85, 0.49)),
    ((1.07, 0.25, 0.44), (1.22, 0.58, 0.31)),
    ((1.21, 0.75, 0.38), (1.08, 0.38, 0.52)),
    ((1.13, 0.85, 0.46), (1.19, 0.17, 0.51)),
)


def ffmpeg(scratch, *arguments):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments],
        cwd=scratch, check=True,
    )


def animate(still, clip, frames, size, move, previous_end, scratch, strip=False):
    width, height = size
    progress = f"(on/{max(1, frames - 1)})"
    start, end = move
    zoom, x, y = [f"{a}+({b - a})*{progress}" for a, b in zip(start, end)]
    camera = (
        f"scale={width * 2}:{height * 2},"
        f"zoompan=z='{zoom}':x='(iw-iw/zoom)*({x})':y='(ih-ih/zoom)*({y})':"
        f"d={frames}:s={width}x{height}:fps={FPS},format=yuv420p"
    )
    if strip:
        strip_progress = f"min(n/{max(1, frames - 1)},1)"
        camera = f"crop={width}:{height}:x='(iw-ow)*{strip_progress}':y=0,format=yuv420p"
    transition = min(6, frames - 1)
    if previous_end is not None and transition > 0:
        overlay = (
            f"[0:v]{camera}[picture];"
            f"[1:v]format=yuva420p,fade=t=out:s=0:n={transition}:alpha=1[previous];"
            "[picture][previous]overlay=eof_action=pass[out]"
        )
        filters = [
            "-loop", "1", "-framerate", str(FPS), "-t", f"{(transition + 1) / FPS:.6f}",
            "-i", previous_end.name, "-filter_complex", overlay, "-map", "[out]",
        ]
    else:
        filters = ["-vf", camera]
    source = ["-loop", "1", "-framerate", str(FPS)] if strip else []
    ffmpeg(scratch, "-filter_threads", "1", "-filter_complex_threads", "1", *source, "-i", still.name, *filters,
           "-frames:v", str(frames), "-c:v", "libx264", "-threads", "3",
           "-preset", "veryfast", "-crf", "16", "-an", clip.name)


def camera_end(image, position):
    zoom, x, y = position
    width, height = image.size
    crop_width, crop_height = width / zoom, height / zoom
    left = (width - crop_width) * x
    top = (height - crop_height) * y
    return image.resize(image.size, Image.Resampling.LANCZOS, box=(left, top, left + crop_width, top + crop_height))


def picture_path(source, job_dir, images_dir):
    """src: art/<file> (repo library), own/<file> (lore/<N>/own/), or <round>/<file> from the searches."""
    folder, _, name = source.partition("/")
    root = {"art": ART_ROOT, "own": job_dir / "own"}.get(folder, images_dir / folder)
    path = (root / name).resolve()
    if not name or not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Không tìm thấy ảnh {source}.")
    return path


def load_images(images, job_dir, images_dir):
    pictures = {}
    for name, entry in images.items():
        picture = open_picture(picture_path(entry["src"], job_dir, images_dir))
        if entry.get("crop"):
            x0, y0, x1, y1 = entry["crop"]
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError(f"Ảnh {name}: crop là [x0, y0, x1, y1] trong khoảng 0–1.")
            width, height = picture.size
            picture = picture.crop((round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height)))
        pictures[name] = picture
    return pictures


def shot_picture(shot, index, images, pictures, size):
    """The still of one shot (twice as wide for a panned collage) and its camera move."""
    width, height = size
    move = CAMERA_MOVES[index % len(CAMERA_MOVES)]
    move = (tuple(shot.get("from") or move[0]), tuple(shot.get("to") or move[1]))
    if "theme" in shot and "img" not in shot and "collage" not in shot:
        return atmosphere(size, shot["theme"], seed=2099 + 37 * index), move
    if "collage" in shot:
        target = (width * 2, height) if shot.get("pan") else size
        return opening_collage([pictures[name] for name in shot["collage"]], target), move
    focal = tuple(images[shot["img"]].get("focal", (0.5, 0.42)))
    return fit_picture(pictures[shot["img"]], size, focal), move


def shot_views(picture, move, size):
    """What the viewer sees at the start and at the end of the shot."""
    if picture.width > size[0]:
        return picture.crop((0, 0, size[0], size[1])), picture.crop((picture.width - size[0], 0, picture.width, size[1]))
    return camera_end(picture, move[0]), camera_end(picture, move[1])


def shot_credits(shot, images):
    names = [shot["img"]] if "img" in shot else shot.get("collage", [])
    return [images[name]["credit"] for name in names]


def write_credits(scenes, path):
    lines = ["# Nguồn hình", ""]
    seen = set()
    for scene in scenes:
        for credit in scene["credits"]:
            if credit not in seen:
                seen.add(credit)
                lines.append(f"- {credit}")
    if not seen:
        lines.append("- Đồ họa nền tạo bằng mã của repo.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_sheet(video, scenes, scratch, path):
    tiles = []
    for number, scene in enumerate(scenes, start=1):
        moment = (scene["start"] + scene["end"]) / 2
        ffmpeg(scratch, "-ss", f"{moment:.2f}", "-i", str(video), "-frames:v", "1", "sheet.png")
        with Image.open(scratch / "sheet.png") as frame:
            tile = frame.convert("RGB").resize((216, 384))
        tiles.append((tile, f"{number}  {scene['picture']}  {scene['start']:.0f}s"[:34]))
    contact_sheet(tiles, path, columns=6)


def mux_video(audio, frames, scratch, destination):
    duration = frames / FPS
    ambient = (
        "aevalsrc=0.012*sin(2*PI*46*t)+0.006*sin(2*PI*69*t)*(0.6+0.4*sin(2*PI*0.17*t))"
        f":s=48000:d={duration:.6f}"
    )
    fade = min(0.8, duration / 3)
    mix = (
        "[1:a]loudnorm=I=-17:TP=-2:LRA=7,aresample=48000,apad[voice];"
        f"[2:a]afade=d={fade},afade=t=out:st={duration - fade}:d={fade}[bed];"
        "[voice][bed]amix=inputs=2:normalize=0,alimiter=limit=0.88:level=0[audio]"
    )
    ffmpeg(
        scratch, "-filter_threads", "1", "-filter_complex_threads", "1",
        "-f", "concat", "-safe", "1", "-i", "shots.txt", "-i", audio.name, "-f", "lavfi", "-i", ambient,
        "-vf", "ass=subtitles.ass", "-filter_complex", mix, "-map", "0:v", "-map", "[audio]",
        "-frames:v", str(frames), "-t", f"{duration:.6f}", "-c:v", "libx264",
        "-threads", "3", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(destination),
    )


def render(job_dir, voice_dir, images_dir, out, size_name="full"):
    job = load_job(job_dir / "script.json")
    timing = json.loads((voice_dir / "timing.json").read_text(encoding="utf-8"))
    if timing["text"] != job.text:
        raise ValueError("Giọng đọc đã lưu không khớp script.json. Chạy lại bước prepare.")
    images, shots = load_picks(job_dir / "picks.json", len(job.spans))
    audio = voice_dir / timing["audio"]
    out = out.resolve()
    if out.exists():
        raise ValueError("Hãy chọn thư mục xuất mới để giữ các bản dựng trước.")
    out.parent.mkdir(parents=True, exist_ok=True)
    size = SIZES[size_name]
    with tempfile.TemporaryDirectory(prefix=".render-", dir=out.parent) as temporary:
        scratch = Path(temporary)
        stage = scratch / "result"
        stage.mkdir()
        shutil.copyfile(audio, scratch / audio.name)
        duration = audio_duration(audio)
        frames = math.ceil(duration * FPS)
        starts, ends = timing["starts"], timing["ends"]
        cues = make_cues(job.text, starts, ends, duration)
        times = line_times(job.spans, starts, ends)
        ranges = shot_frames(shots, times, frames, FPS)
        write_subtitles(cues, stage / "subtitles.srt", scratch / "subtitles.ass",
                        job.title, opening_frames(frames, FPS) / FPS)
        pictures = load_images(images, job_dir, images_dir)

        scenes = []
        playlist = []
        previous_end = scratch / "camera-end.png"
        for index, (shot, (first, last)) in enumerate(zip(shots, ranges)):
            picture, move = shot_picture(shot, index, images, pictures, size)
            picture = grade_frame(picture)
            still = scratch / f"shot-{index:03}.png"
            clip = scratch / f"shot-{index:03}.mp4"
            picture.save(still)
            strip = picture.width > size[0]
            animate(still, clip, last - first, size, move, previous_end if index else None, scratch, strip=strip)
            shot_views(picture, move, size)[1].save(previous_end)
            playlist.append(f"file '{clip.name}'")
            scenes.append({
                "start": round(first / FPS, 3),
                "end": round(last / FPS, 3),
                "picture": shot.get("img") or "+".join(shot.get("collage", [])) or shot["theme"],
                "text": " ".join(job.text[a:b] for (a, b), (begin, _) in zip(job.spans, times)
                                 if first <= round(begin * FPS) < last),
                "credits": shot_credits(shot, images),
            })

        (scratch / "shots.txt").write_text("\n".join(playlist) + "\n", encoding="ascii")
        mux_video(scratch / audio.name, frames, scratch, stage / "video.mp4")
        ffmpeg(scratch, "-i", str(stage / "video.mp4"), "-frames:v", "1", "-q:v", "2", str(stage / "cover.jpg"))
        write_sheet(stage / "video.mp4", scenes, scratch, stage / "sheet.jpg")
        write_credits(scenes, stage / "credits.md")
        (stage / "scenes.json").write_text(
            json.dumps({"title": job.title, "duration": round(duration, 3), "scenes": scenes},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        stage.rename(out)
    return duration, len(scenes)


def main():
    parser = argparse.ArgumentParser(description="Dựng video dọc Warhammer 40K từ script.json và picks.json.")
    parser.add_argument("--job", type=Path, required=True, help="thư mục lore/<N>")
    parser.add_argument("--voice", type=Path, required=True, help="thư mục có timing.json và tệp giọng")
    parser.add_argument("--images", type=Path, required=True, help="thư mục ảnh đã tìm (img/)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", choices=tuple(SIZES), default="full")
    args = parser.parse_args()
    for command in ("ffmpeg", "ffprobe"):
        if not shutil.which(command):
            parser.error(f"Thiếu {command}.")
    try:
        duration, count = render(args.job, args.voice, args.images, args.out, args.size)
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Lỗi dựng video: {error}\n")
    print(f"Xuất {count} cảnh, {duration:.1f} giây: {args.out}")


if __name__ == "__main__":
    main()
