"""Voice of one video: VN11 reads the whole script in one take, Whisper times it against the script.

Usage: python3 -m factory.narrate --job lore/<N> --out <voice folder> [--previous <voice folder of the last run>]
Writes narration.mp3, timing.json (time of every character and line) and check.md (words Whisper heard differently).
An unchanged script with the same voice reuses the previous take instead of paying for a new one.
"""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from .script import line_times, load_job
from .vn11 import configuration, synthesize
from .voice import audio_duration
from .voice_check import align_words, load_model, transcribe

LANGUAGE = "de"


def write_timing(job, voice, audio_name, duration, starts, ends, report, out):
    lines = [{"n": number, "start": round(start, 3), "end": round(end, 3), "text": job.text[first:last]}
             for number, ((first, last), (start, end))
             in enumerate(zip(job.spans, line_times(job.spans, starts, ends)), start=1)]
    timing = {
        "text": job.text, "voice": voice, "audio": audio_name, "duration": round(duration, 3),
        "match": report["match"], "lines": lines, "review": report["review"],
        "starts": [round(value, 3) for value in starts], "ends": [round(value, 3) for value in ends],
    }
    (out / "timing.json").write_text(json.dumps(timing, ensure_ascii=False) + "\n", encoding="utf-8")
    check = [f"# Kiểm tra giọng đọc", "", f"Whisper nghe khớp {report['match']:.0%} với kịch bản.", ""]
    for item in report["review"]:
        check.append(f"- {item['start']:.1f}s — kịch bản: «{item['script']}» · nghe được: «{item['heard']}»")
    if not report["review"]:
        check.append("Không có đoạn nào cần nghe lại.")
    (out / "check.md").write_text("\n".join(check) + "\n", encoding="utf-8")
    return timing


def narrate(job, out, previous=None):
    key, voice = configuration()
    voice = job.voice or voice
    out.mkdir(parents=True, exist_ok=True)
    if previous and (previous / "timing.json").is_file():
        old = json.loads((previous / "timing.json").read_text(encoding="utf-8"))
        if old.get("text") == job.text and old.get("voice") == voice and (previous / old["audio"]).is_file():
            if previous.resolve() != out.resolve():
                shutil.copytree(previous, out, dirs_exist_ok=True)
            return old, True
    model = load_model()
    with tempfile.TemporaryDirectory() as temporary:
        audio = synthesize(job.text, LANGUAGE, Path(temporary), key, voice)
        duration = audio_duration(audio)
        starts, ends, report = align_words(job.text, transcribe(model, audio, LANGUAGE), duration)
        shutil.copyfile(audio, out / "narration.mp3")
    return write_timing(job, voice, "narration.mp3", duration, starts, ends, report, out), False


def main():
    parser = argparse.ArgumentParser(description="Tạo giọng đọc và mốc thời gian cho một phiếu.")
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    try:
        timing, reused = narrate(load_job(args.job / "script.json"), args.out, args.previous)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Không tạo được giọng đọc: {error}\n")
    print(f"{'Dùng lại' if reused else 'Đã tạo'} giọng đọc {timing['duration']:.1f} giây, khớp {timing['match']:.0%}.")


if __name__ == "__main__":
    main()
