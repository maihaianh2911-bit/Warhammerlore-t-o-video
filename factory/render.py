import argparse
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .art import ART_ROOT, atmosphere, contact_sheet, fit_picture, grade_frame, open_picture
from .script import (
    caption_chunks, line_times, load_job, load_picks, make_cues, opening_frames, shot_frames, write_subtitles,
)
from .voice import audio_duration


FPS = 30
SIZES = {"preview": (720, 1280), "full": (1080, 1920)}
ZOOM_PER_SECOND = 0.032     # the reference video pushes in at an even ~3% of the frame per second
MAX_AUTO_ZOOM = 1.42
DETAIL = 1.5                # stills are kept larger than the frame so a push-in stays sharp
FONTS = Path(__file__).resolve().parent.parent / "fonts"


def ffmpeg(scratch, *arguments, **options):
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments],
        cwd=scratch, check=True, **options,
    )


def default_move(focus, seconds):
    """An even push-in towards the focus point, as in the reference: the point stays put, the rest grows."""
    x, y = focus
    return (1.0, x, y), (min(1.0 + ZOOM_PER_SECOND * seconds, MAX_AUTO_ZOOM), x, y)


def camera_view(image, position, size):
    """The frame at one camera position [zoom, x, y]; fractional crops keep slow moves free of jitter."""
    zoom, x, y = position
    width, height = image.size
    crop_width, crop_height = width / zoom, height / zoom
    left = (width - crop_width) * x
    top = (height - crop_height) * y
    return image.resize(size, Image.Resampling.BICUBIC, box=(left, top, left + crop_width, top + crop_height))


def shot_frames_rgb(image, move, count, size):
    start, end = move
    for index in range(count):
        progress = index / max(1, count - 1)
        position = [a + (b - a) * progress for a, b in zip(start, end)]
        yield camera_view(image, position, size).tobytes()


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


def shot_picture(shot, index, images, pictures, size, seconds):
    """The still of one shot (larger than the frame) and its camera move (start, end)."""
    large = (round(size[0] * DETAIL), round(size[1] * DETAIL))
    if "img" in shot:
        entry = images[shot["img"]]
        picture = fit_picture(pictures[shot["img"]], large, tuple(entry.get("focal", (0.5, 0.42))))
    else:
        picture = atmosphere(size, shot["theme"], seed=2099 + 37 * index).resize(large, Image.Resampling.BICUBIC)
    start, end = default_move(shot.get("focus", (0.5, 0.4)), seconds)
    if "zoom" in shot:
        end = (shot["zoom"], *end[1:])
    return picture, (tuple(shot.get("from") or start), tuple(shot.get("to") or end))


def shot_views(picture, move, size):
    """What the viewer sees at the start and at the end of the shot."""
    return camera_view(picture, move[0], size), camera_view(picture, move[1], size)


def shot_credits(shot, images):
    return [images[shot["img"]]["credit"]] if "img" in shot else []


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


def encode_video(frames_rgb, audio, frames, size, scratch, destination):
    """Frames from Python, subtitles, voice and a quiet bed, in one pass."""
    duration = frames / FPS
    ambient = (
        "aevalsrc=0.012*sin(2*PI*46*t)+0.006*sin(2*PI*69*t)*(0.6+0.4*sin(2*PI*0.17*t))"
        f":s=48000:d={duration:.6f}"
    )
    fade = min(0.8, duration / 3)
    mix = (
        f"[0:v]ass=subtitles.ass:fontsdir={FONTS},format=yuv420p[video];"
        "[1:a]loudnorm=I=-17:TP=-2:LRA=7,aresample=48000,apad[voice];"
        f"[2:a]afade=d={fade},afade=t=out:st={duration - fade}:d={fade}[bed];"
        "[voice][bed]amix=inputs=2:normalize=0,alimiter=limit=0.88:level=0[audio]"
    )
    process = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-",
         "-i", audio.name, "-f", "lavfi", "-i", ambient,
         "-filter_complex", mix, "-map", "[video]", "-map", "[audio]",
         "-frames:v", str(frames), "-t", f"{duration:.6f}", "-c:v", "libx264",
         "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", str(destination)],
        cwd=scratch, stdin=subprocess.PIPE,
    )
    try:
        for frame in frames_rgb:
            process.stdin.write(frame)
        process.stdin.close()
    except BrokenPipeError:
        pass
    if process.wait():
        raise RuntimeError("FFmpeg không xuất được video.")


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
        write_subtitles(cues, caption_chunks(job.text, starts, ends, duration), duration,
                        stage / "subtitles.srt", scratch / "subtitles.ass",
                        job.title, opening_frames(frames, FPS) / FPS)
        pictures = load_images(images, job_dir, images_dir)

        scenes = []
        stills = []
        for index, (shot, (first, last)) in enumerate(zip(shots, ranges)):
            picture, move = shot_picture(shot, index, images, pictures, size, (last - first) / FPS)
            stills.append((grade_frame(picture), move, last - first))
            scenes.append({
                "start": round(first / FPS, 3),
                "end": round(last / FPS, 3),
                "picture": shot.get("img") or shot["theme"],
                "text": " ".join(job.text[a:b] for (a, b), (begin, _) in zip(job.spans, times)
                                 if first <= round(begin * FPS) < last),
                "credits": shot_credits(shot, images),
            })

        frames_rgb = (frame for picture, move, count in stills
                      for frame in shot_frames_rgb(picture, move, count, size))
        encode_video(frames_rgb, scratch / audio.name, frames, size, scratch, stage / "video.mp4")
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
