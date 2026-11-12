import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from itertools import chain, islice
from pathlib import Path

from PIL import Image

from .art import (
    atmosphere, choose_art, fit_picture, grade_frame, load_catalog, mentioned_subjects, opening_collage, read_picture,
)
from .script import make_cues, make_shots, opening_frames, read_script, write_subtitles
from .voice import audio_duration, elevenlabs, preview_voice
from .vn11 import LANGUAGES, configuration as vn11_configuration, synthesize as vn11_synthesize
from .voice_check import align_words, load_model, transcribe


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


def build_picture(catalog, shot, size, previous, index, cache, context):
    theme, references, assets = choose_art(catalog, shot.text, previous, index, context)
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


def shot_pictures(catalog, shots, size):
    previous = None
    context = ""
    cache = {}
    for index, shot in enumerate(shots):
        picture, details = build_picture(catalog, shot, size, previous, index, cache, context)
        if mentioned_subjects(catalog, shot.text):
            context = shot.text
        previous = details["art"]["source"] if details["art"] else None
        yield picture, details


def opening_sequence(candidates, size):
    _, first = candidates[0]
    artwork = {}
    backgrounds = {}
    for candidate, details in candidates:
        if details["art"]:
            artwork.setdefault(details["art"]["source"], (candidate, details))
        else:
            backgrounds.setdefault(details["theme"], (candidate, details))
    selected = list((artwork or backgrounds).values())
    if len(selected) == 1:
        return [selected[0]]
    pictures, details = zip(*selected)
    credits = [item["art"] for item in details if item["art"]]
    references = {reference["url"]: reference for item in details for reference in item["references"]}
    montage_details = {
        "theme": first["theme"], "art": credits[0] if credits else None, "additional_art": credits[1:],
        "references": list(references.values()), "unavailable": first["unavailable"],
    }
    width, height = size
    return [
        (opening_collage(pictures, size), montage_details),
        (opening_collage(pictures, (width * 2, height)), montage_details),
    ]


def write_credits(scenes, path):
    lines = ["# Nguồn hình", ""]
    for scene in scenes:
        lines.append(f"## {scene['start']:.1f}–{scene['end']:.1f}s")
        lines.append("")
        credits = ([scene["art"]] if scene["art"] else []) + scene.get("additional_art", [])
        for credit in credits:
            lines.append(f"- Hình đã dùng: {credit['title']} — {credit['artist']}.")
            lines.append(f"- Nguồn và quyền sử dụng: {credit['source']} · {credit['rights']}")
        if not credits:
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
        if args.voice == "vn11":
            key, voice_id = vn11_configuration()
            model = load_model()
            audio = vn11_synthesize(text, args.language, scratch, key, voice_id)
            duration = audio_duration(audio)
            starts, ends, report = align_words(text, transcribe(model, audio, args.language), duration)
            (stage / "voice-check.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
            shutil.copyfile(audio, stage / "narration.mp3")
        elif args.voice == "elevenlabs":
            audio, starts, ends = elevenlabs(text, args.language, scratch)
            duration = audio_duration(audio)
        else:
            audio, starts, ends = preview_voice(text, args.language, scratch, args.voice)
            duration = audio_duration(audio)
        frames = math.ceil(duration * FPS)
        cues = make_cues(text, starts, ends, duration)
        def subjects(line):
            return {subject["name"] for subject in mentioned_subjects(catalog, line)}

        shots = make_shots(cues, frames, FPS, subjects)
        write_subtitles(cues, stage / "subtitles.srt", scratch / "subtitles.ass",
                        args.title, opening_frames(frames, FPS) / FPS)

        scenes = []
        playlist = []
        size = SIZES[args.size]
        pictures = shot_pictures(catalog, shots, size)
        introduction = list(islice(pictures, 3))
        opening = opening_sequence(introduction, size)
        pictures = chain(opening, introduction[len(opening):], pictures)
        previous_end = scratch / "camera-end.png"
        for index, (shot, (picture, details)) in enumerate(zip(shots, pictures)):
            picture = grade_frame(picture)
            still = scratch / f"shot-{index:03}.png"
            clip = scratch / f"shot-{index:03}.mp4"
            picture.save(still)
            move = CAMERA_MOVES[index % len(CAMERA_MOVES)]
            strip = picture.width > size[0]
            animate(still, clip, shot.end_frame - shot.start_frame, size, move,
                    previous_end if index else None, scratch, strip=strip)
            if strip:
                picture.crop((picture.width - size[0], 0, picture.width, picture.height)).save(previous_end)
            else:
                camera_end(picture, move[1]).save(previous_end)
            playlist.append(f"file '{clip.name}'")
            scenes.append({
                "start": round(shot.start_frame / FPS, 3),
                "end": round(shot.end_frame / FPS, 3),
                "text": shot.text,
                "layout": "horizontal_pan" if strip else "full_frame",
                **details,
            })

        (scratch / "shots.txt").write_text("\n".join(playlist) + "\n", encoding="ascii")
        mux_video(audio, frames, scratch, stage / "video.mp4")
        ffmpeg(scratch, "-i", str(stage / "video.mp4"), "-frames:v", "1", "-q:v", "2", str(stage / "cover.jpg"))
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
    parser.add_argument("--language", choices=tuple(LANGUAGES), default="de")
    default_voice = "espeak"
    if os.environ.get("ELEVENLABS_API_KEY"):
        default_voice = "elevenlabs"
    if os.environ.get("VN11_API_KEY"):
        default_voice = "vn11"
    parser.add_argument("--voice", choices=("vn11", "elevenlabs", "espeak", "flite"), default=default_voice)
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
