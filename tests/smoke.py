"""Render a made-up video end to end without VN11, Whisper or the network: a silent voice track with even
timings, two generated pictures and a generated background. Usage: python3 tests/smoke.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from factory.art import atmosphere
from factory.narrate import write_timing
from factory.preview import preview
from factory.render import render
from factory.script import load_job

SCRIPT = {
    "title": "Wer öffnet das Tor im 41. Jahrtausend?",
    "paragraphs": [
        ["Im 41. Jahrtausend gibt es nur Krieg.", "Slaanesh erscheint zuerst im violetten Licht."],
        ["Tzeentch folgt in Blau – das Bild gleitet weiter.", "Khorne schließt in Rot."],
    ],
}
PICKS = {
    "images": {
        "rift": {"src": "own/rift.jpg", "credit": "Testbild A", "focal": [0.5, 0.4]},
        "orbit": {"src": "issue/1.jpg", "credit": "Testbild B", "crop": [0.1, 0.0, 0.9, 1.0]},
    },
    "shots": [
        {"img": "orbit", "focus": [0.7, 0.3]},
        {"at": 2, "img": "rift", "from": [1.0, 0.5, 0.5], "to": [1.3, 0.5, 0.3]},
        {"at": 3, "img": "orbit", "zoom": 1.5},
        {"at": 4, "theme": "inferno"},
    ],
}

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    job_dir, voice, images = root / "lore" / "1", root / "voice", root / "img"
    (job_dir / "own").mkdir(parents=True)
    (images / "issue").mkdir(parents=True)
    voice.mkdir()
    (job_dir / "script.json").write_text(json.dumps(SCRIPT, ensure_ascii=False), encoding="utf-8")
    (job_dir / "picks.json").write_text(json.dumps(PICKS), encoding="utf-8")
    atmosphere((720, 1280), "rift", 1).save(job_dir / "own" / "rift.jpg")
    atmosphere((1280, 720), "orbit", 2).save(images / "issue" / "1.jpg")

    job = load_job(job_dir / "script.json")
    step = 0.07
    duration = len(job.text) * step
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", f"{duration:.3f}", str(voice / "narration.wav")], check=True)
    starts = [index * step for index in range(len(job.text))]
    ends = [start + step for start in starts]
    write_timing(job, "test", "narration.wav", duration, starts, ends, {"match": 1.0, "review": []}, voice)

    assert preview(job_dir, images, root / "preview.jpg") == 4
    length, count = render(job_dir, voice, images, root / "out", "preview")
    scenes = json.loads((root / "out" / "scenes.json").read_text(encoding="utf-8"))["scenes"]
    assert count == 4 and abs(length - duration) < 0.2, (count, length)
    assert [scene["picture"] for scene in scenes] == ["orbit", "rift", "orbit", "inferno"], scenes
    assert scenes[1]["text"] == SCRIPT["paragraphs"][0][1], scenes[1]
    for name in ("video.mp4", "subtitles.srt", "cover.jpg", "sheet.jpg", "credits.md"):
        assert (root / "out" / name).stat().st_size > 0, name
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(root / "out" / "video.mp4")], capture_output=True, text=True, check=True)
    assert probe.stdout.strip() == "720,1280", probe.stdout
    if len(sys.argv) > 1:   # keep the sheets to look at
        for name in ("preview.jpg", "out/sheet.jpg", "out/credits.md", "out/subtitles.srt"):
            (Path(sys.argv[1]) / Path(name).name).write_bytes((root / name).read_bytes())
print("smoke ok")
