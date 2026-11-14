"""Voice of one video: VN11 reads the whole script in one take, Whisper times it against the script.

Usage: python3 -m factory.narrate --job lore/<N> --out <voice folder> [--previous <voice folder of the last run>]
Writes narration.mp3, timing.json (time of every character and line) and check.md (words Whisper heard differently).
An unchanged script with the same voice reuses the previous take instead of paying for a new one.

A reading is paid for, so it is never thrown away: the VN11 job id is written to pending.json as soon as VN11 has
accepted the text, and the audio to take.mp3 as soon as it is downloaded — both before Whisper checks it, and each
time `checkpoint` is called so the caller can store the folder (factory.run publishes it). A later run with the
same text and voice continues from there instead of paying again. pending.json and take.mp3 go away once
narration.mp3 and timing.json are written.
"""
import argparse
import json
import shutil
from pathlib import Path

from .script import line_times, load_job
from .vn11 import JobLost, configuration, create_job, poll_job, save_audio
from .voice import audio_duration
from .voice_check import align_words, load_model, transcribe

LANGUAGE = "de"
PENDING = "pending.json"    # {"text", "voice", "job"[, "audio"]}: a reading that is paid for but not checked yet
TAKE = "take.mp3"


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


def take(text, voice, key, out, checkpoint=None):
    """out/take.mp3: VN11's reading of this text, paid for at most once across runs."""
    save = checkpoint or (lambda: None)
    note, audio = out / PENDING, out / TAKE
    try:
        pending = json.loads(note.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pending = {}
    if pending.get("text") != text or pending.get("voice") != voice:
        pending = {}                                      # a reading of another script: of no use
        audio.unlink(missing_ok=True)
    if pending.get("audio") and audio.is_file():
        print("Dùng lại bản đọc đã trả tiền (take.mp3).", flush=True)
        return audio
    if pending.get("job"):
        print("Lấy tiếp lượt tạo giọng đã gửi ở lần chạy trước, không tạo lượt mới.", flush=True)
    else:
        pending = {"text": text, "voice": voice, "job": create_job(text, LANGUAGE, key, voice)}
        note.write_text(json.dumps(pending, ensure_ascii=False) + "\n", encoding="utf-8")
        save()                                            # from here on the reading is paid for
    try:
        save_audio(poll_job(pending["job"], key), audio)
    except JobLost as error:
        note.unlink(missing_ok=True)
        save()
        raise RuntimeError(f"{error} Lượt tạo giọng này không lấy lại được: lần chạy sau sẽ gửi lượt mới.") from None
    pending["audio"] = TAKE
    note.write_text(json.dumps(pending, ensure_ascii=False) + "\n", encoding="utf-8")
    save()
    return audio


def narrate(job, out, previous=None, checkpoint=None):
    key, voice = configuration()
    voice = job.voice or voice
    out.mkdir(parents=True, exist_ok=True)
    if previous and (previous / "timing.json").is_file():
        old = json.loads((previous / "timing.json").read_text(encoding="utf-8"))
        if old.get("text") == job.text and old.get("voice") == voice and (previous / old["audio"]).is_file():
            if previous.resolve() != out.resolve():
                shutil.copytree(previous, out, dirs_exist_ok=True)
            return old, True
    model = load_model()                                  # before paying: without Whisper nothing can be checked
    audio = take(job.text, voice, key, out, checkpoint)
    try:
        duration = audio_duration(audio)
        starts, ends, report = align_words(job.text, transcribe(model, audio, LANGUAGE), duration)
    except ValueError as error:
        raise ValueError(
            f"{error} Bản đọc đã trả tiền vẫn được giữ (voice/{TAKE}): chạy lại không tốn thêm tiền. "
            "Nghe thử file đó; nếu giọng đọc sai thì sửa lời trong script.json (đổi lời thì VN11 đọc lại, có tốn tiền)."
        ) from None
    shutil.copyfile(audio, out / "narration.mp3")
    timing = write_timing(job, voice, "narration.mp3", duration, starts, ends, report, out)
    audio.unlink()
    (out / PENDING).unlink(missing_ok=True)
    return timing, False


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
