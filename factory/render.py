import argparse
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .art import ART_ROOT, atmosphere, contact_sheet, grade_frame, open_picture
from .script import (
    MOVES, caption_chunks, line_times, load_job, load_picks, make_cues, opening_frames, shot_frames, write_subtitles,
)
from .voice import audio_duration


FPS = 30
SIZES = {"preview": (720, 1280), "full": (1080, 1920)}
ZOOM_PER_SECOND = 0.045     # how fast a shot closes in; the reference video does about 0.03
DETAIL = 1.7                # stills are kept larger than the frame so a deep push-in stays sharp
KICK = 0.03                 # default extra push a cut lands with; it settles in a third of a second
KICK_SECONDS = 0.33
FONTS = Path(__file__).resolve().parent.parent / "fonts"


def ffmpeg(scratch, *arguments, **options):
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments],
        cwd=scratch, check=True, **options,
    )


BLEND_FRAMES = 4            # a cut is softened over a few frames


def view_share(shape, zoom):
    """Width and height of the camera's view as fractions of the picture. shape = (width, height, frame aspect).

    At zoom 1 the view is the largest frame-shaped window the picture holds, so a wide picture has room to
    travel sideways and a tall one up and down even before zooming.
    """
    width, height, aspect = shape
    base_width = min(width, height * aspect)
    return base_width / width / zoom, base_width / aspect / height / zoom


def centred(zoom, point, shape):
    """Camera position (zoom, x, y) looking at a point of the picture, kept inside the picture's edges."""
    return (zoom, *(min(1 - share / 2, max(share / 2, value)) for value, share in zip(point, view_share(shape, zoom))))


def default_move(focus, seconds, kind, shape):
    """Two keyframes of a shot, start and end. Every move ends centred on the focus point (the subject).

    push        the widest view of the picture, then a push-in on the subject
    pull        starts closer on the subject and draws back to show it in its setting, still centred on it
    rise, fall  starts well below / above the subject and travels to it while closing in
    from-left, from-right   starts far to that side of the subject and sweeps across to it while closing in
    glide       from-left or from-right, whichever side has more picture
    """
    x, y = focus
    drift = ZOOM_PER_SECOND * seconds
    # an off-centre subject can only be brought to the middle of the frame from a certain zoom on
    wide, tall = view_share(shape, 1.0)
    needed = min(1.3, max(1.1, wide / 2 / max(0.05, min(x, 1 - x)), tall / 2 / max(0.05, min(y, 1 - y))))
    if kind == "push":
        return centred(1.0, (0.5, 0.5), shape), centred(min(max(1.0 + drift, needed, 1.2), 1.42), focus, shape)
    if kind == "pull":
        return centred(min(needed + max(drift, 0.28), 1.6), focus, shape), centred(needed, focus, shape)
    travel = min(0.6, 0.1 * seconds + 0.2)          # share of the picture crossed on the way to the subject
    if kind == "glide":
        kind = "from-right" if x < 0.5 else "from-left"
    origin = {
        "rise": (x, y + travel), "fall": (x, y - travel),
        "from-left": (x - travel, y), "from-right": (x + travel, y),
    }[kind]
    start_zoom = max(1.2, needed)     # close enough to travel, wide enough to keep the scene
    return centred(start_zoom, origin, shape), centred(min(start_zoom + drift * 0.6, 1.45), focus, shape)


PACES = {
    "settle": lambda t: 0.3 * t + 0.7 * (1 - (1 - t) ** 2),    # leaves briskly, eases onto the subject
    "even": lambda t: t,                                        # a steady keyframe move, as in the reference
    "surge": lambda t: 0.35 * t + 0.65 * t ** 2,                # starts quietly and gathers speed into the subject
}


def eased(progress, pace="settle"):
    return PACES[pace](progress)


def along(keys, progress):
    """Camera position at a point of the path through the keyframes [(time 0–1, (zoom, x, y)), ...]."""
    for (t0, first), (t1, second) in zip(keys, keys[1:]):
        if progress <= t1:
            share = (progress - t0) / (t1 - t0)
            return tuple(a + (b - a) * share for a, b in zip(first, second))
    return keys[-1][1]


def camera_view(image, position, size):
    """The frame at one camera position (zoom, x, y); fractional crops keep slow moves free of jitter."""
    shape = (*image.size, size[0] / size[1])
    zoom, x, y = centred(position[0], position[1:], shape)
    wide, tall = view_share(shape, zoom)
    width, height = image.size
    left, top = (x - wide / 2) * width, (y - tall / 2) * height
    return image.resize(size, Image.Resampling.BICUBIC, box=(left, top, left + wide * width, top + tall * height))


def shot_frames_rgb(image, plan, count, size, previous=None):
    """Frames of one shot, blended out of the last frame of the shot before."""
    for index in range(count):
        zoom, x, y = along(plan["keys"], eased(index / max(1, count - 1), plan["pace"]))
        landing = max(0.0, 1 - index / (KICK_SECONDS * FPS))
        frame = camera_view(image, (zoom * (1 + plan["kick"] * landing ** 3), x, y), size)
        if previous is not None and index < BLEND_FRAMES:
            frame = Image.blend(previous, frame, (index + 1) / (BLEND_FRAMES + 1))
        yield frame


def all_frames(stills, size):
    """stills yields (picture, camera plan, frame count) one shot at a time, so only one large picture is in memory."""
    previous = None
    for picture, plan, count in stills:
        for frame in shot_frames_rgb(picture, plan, count, size, previous):
            yield frame.tobytes()
        previous = frame


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
    """The still of one shot (the whole picture, enlarged for sharp push-ins) and its camera move (start, end)."""
    aspect = size[0] / size[1]
    if "img" in shot:
        picture = pictures[shot["img"]]
        width, height = picture.size
        scale = size[0] * DETAIL / min(width, height * aspect)
        picture = picture.resize((round(width * scale), round(height * scale)), Image.Resampling.LANCZOS)
    else:
        picture = atmosphere(size, shot["theme"], seed=2099 + 37 * index)
        picture = picture.resize((round(size[0] * DETAIL), round(size[1] * DETAIL)), Image.Resampling.BICUBIC)
    shape = (*picture.size, aspect)
    focus = tuple(shot.get("focus", (0.5, 0.4)))
    start, end = default_move(focus, seconds, shot.get("move") or "push", shape)
    if "zoom" in shot:
        end = centred(shot["zoom"], focus, shape)      # whatever the zoom, the shot ends on the subject
    if "from" in shot:
        start = centred(shot["from"][0], shot["from"][1:], shape)
    keys = [(0.0, start), *((t, centred(zoom, (x, y), shape)) for t, zoom, x, y in shot.get("via", [])), (1.0, end)]
    return picture, {"keys": keys, "pace": shot.get("pace", "settle"), "kick": shot.get("kick", KICK)}


def shot_views(picture, plan, size):
    """What the viewer sees at every keyframe of the shot, first to last."""
    return [camera_view(picture, position, size) for _, position in plan["keys"]]


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
        f"[0:v]vignette=angle=PI/5.5,ass=subtitles.ass:fontsdir={FONTS},format=yuv420p[video];"
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
        def stills():
            for index, (shot, (first, last)) in enumerate(zip(shots, ranges)):
                picture, plan = shot_picture(shot, index, images, pictures, size, (last - first) / FPS)
                yield grade_frame(picture), plan, last - first

        for shot, (first, last) in zip(shots, ranges):
            scenes.append({
                "start": round(first / FPS, 3),
                "end": round(last / FPS, 3),
                "picture": shot.get("img") or shot["theme"],
                "text": " ".join(job.text[a:b] for (a, b), (begin, _) in zip(job.spans, times)
                                 if first <= round(begin * FPS) < last),
                "credits": shot_credits(shot, images),
            })

        encode_video(all_frames(stills(), size), scratch / audio.name, frames, size, scratch, stage / "video.mp4")
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
