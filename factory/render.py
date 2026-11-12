import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .art import atmosphere, choose_art, dress_frame, fit_picture, load_catalog, read_picture
from .script import make_cues, make_shots, read_script, write_subtitles
from .voice import audio_duration, elevenlabs, preview_voice


FPS = 30
SIZES = {"preview": (720, 1280), "full": (1080, 1920)}


def ffmpeg(scratch, *arguments):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments],
        cwd=scratch, check=True,
    )


def animate(still, clip, frames, size, index, scratch):
    width, height = size
    progress = f"on/{max(1, frames - 1)}"
    zoom = f"1.015+0.05*{progress}" if index % 2 == 0 else f"1.065-0.05*{progress}"
    filter_graph = (
        f"scale={width * 2}:{height * 2},"
        f"zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
        f"d={frames}:s={width}x{height}:fps={FPS},format=yuv420p"
    )
    ffmpeg(scratch, "-filter_threads", "1", "-i", still.name, "-vf", filter_graph,
           "-frames:v", str(frames), "-c:v", "libx264", "-threads", "3",
           "-preset", "veryfast", "-crf", "16", "-an", clip.name)


def build_picture(catalog, shot, size, previous, index, cache):
    theme, references, assets = choose_art(catalog, shot.text, previous, index)
    errors = []
    for asset in assets:
        source = asset["source"]
        try:
            if source not in cache:
                cache[source] = read_picture(asset)
            picture = fit_picture(cache[source], size, tuple(asset.get("focal", (0.5, 0.42))))
        except (OSError, ValueError, KeyError, Image.DecompressionBombError) as error:
            errors.append({"source": source, "reason": type(error).__name__})
            continue
        credit = {key: asset[key] for key in ("title", "artist", "source", "rights")}
        return picture, {"theme": theme, "art": credit, "references": references, "unavailable": errors}
    picture = atmosphere(size, theme, seed=2099 + 37 * index)
    return picture, {"theme": theme, "art": None, "references": references, "unavailable": errors}


def write_credits(scenes, path):
    lines = ["# Nguồn hình", ""]
    for scene in scenes:
        lines.append(f"## {scene['start']:.1f}–{scene['end']:.1f}s")
        lines.append("")
        credit = scene["art"]
        if credit:
            lines.append(f"- Hình đã dùng: {credit['title']} — {credit['artist']}.")
            lines.append(f"- Nguồn và quyền sử dụng: {credit['source']} · {credit['rights']}")
        else:
            lines.append("- Hình đã dùng: đồ họa nền tạo bằng mã của repo.")
        for reference in scene["references"]:
            lines.append(f"- Tham khảo {reference['subject']}: {reference['url']}")
        for error in scene["unavailable"]:
            lines.append(f"- Hình tải không thành công: {error['source']} ({error['reason']}).")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


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
        "-threads", "3", "-preset", "fast", "-crf", "19", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(destination),
    )


def render(args):
    text = read_script(args.script)
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Hãy chọn thư mục xuất mới để giữ các bản dựng trước.")
    out.parent.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog()
    with tempfile.TemporaryDirectory(prefix=".render-", dir=out.parent) as temporary:
        scratch = Path(temporary)
        stage = scratch / "result"
        stage.mkdir()
        if args.voice == "elevenlabs":
            audio, starts, ends = elevenlabs(text, args.language, scratch)
        else:
            audio, starts, ends = preview_voice(text, args.language, scratch, args.voice)
        duration = audio_duration(audio)
        frames = math.ceil(duration * FPS)
        cues = make_cues(text, starts, ends, duration)
        shots = make_shots(cues, frames, FPS)
        write_subtitles(cues, stage / "subtitles.srt", scratch / "subtitles.ass")

        scenes = []
        playlist = []
        previous = None
        cache = {}
        size = SIZES[args.size]
        for index, shot in enumerate(shots):
            picture, details = build_picture(catalog, shot, size, previous, index, cache)
            previous = details["art"]["source"] if details["art"] else None
            dress_frame(picture, args.title if index == 0 else None)
            still = scratch / f"shot-{index:03}.png"
            clip = scratch / f"shot-{index:03}.mp4"
            picture.save(still)
            if index == 0:
                picture.save(stage / "cover.jpg", quality=92)
            animate(still, clip, shot.end_frame - shot.start_frame, size, index, scratch)
            playlist.append(f"file '{clip.name}'")
            scenes.append({
                "start": round(shot.start_frame / FPS, 3),
                "end": round(shot.end_frame / FPS, 3),
                "text": shot.text,
                **details,
            })

        (scratch / "shots.txt").write_text("\n".join(playlist) + "\n", encoding="ascii")
        mux_video(audio, frames, scratch, stage / "video.mp4")
        write_credits(scenes, stage / "credits.md")
        (stage / "scenes.json").write_text(
            json.dumps({"title": args.title, "voice": args.voice, "scenes": scenes}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        stage.rename(out)
    print(f"Xuất {len(shots)} cảnh, {duration:.1f} giây: {out}")


def main():
    parser = argparse.ArgumentParser(description="Dựng video dọc Warhammer 40K từ kịch bản.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--language", choices=("vi", "en"), default="vi")
    parser.add_argument("--voice", choices=("espeak", "elevenlabs", "flite"),
                        default="elevenlabs" if os.environ.get("ELEVENLABS_API_KEY") else "espeak")
    parser.add_argument("--size", choices=tuple(SIZES), default="full")
    args = parser.parse_args()
    if not " ".join(args.title.split()):
        parser.error("Thiếu tiêu đề video.")
    for command in ("ffmpeg", "ffprobe"):
        if not shutil.which(command):
            parser.error(f"Thiếu {command}.")
    try:
        render(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Lỗi dựng video: {error}\n")


if __name__ == "__main__":
    main()
