import base64
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .script import caption_spans


def audio_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    duration = float(result.stdout)
    if not 0 < duration <= 600:
        raise ValueError("Độ dài giọng đọc nằm ngoài giới hạn dựng của bản hiện tại.")
    return duration


def elevenlabs(text, language, scratch):
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")
    if not api_key or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", voice_id):
        raise ValueError("Cần ELEVENLABS_API_KEY và ELEVENLABS_VOICE_ID hợp lệ.")
    request = Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": "eleven_flash_v2_5", "language_code": language}).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=120) as response:
            data = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"ElevenLabs trả về HTTP {error.code}.") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Không kết nối được đến ElevenLabs.") from None

    alignment = data.get("alignment") or {}
    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if "".join(characters) != text or not (len(starts) == len(ends) == len(text)):
        raise ValueError("ElevenLabs không trả đủ mốc thời gian của kịch bản.")
    audio = scratch / "voice.mp3"
    audio.write_bytes(base64.b64decode(data["audio_base64"], validate=True))
    return audio, starts, ends


def preview_voice(text, language, scratch, engine):
    if engine == "flite" and language != "en":
        raise ValueError("Giọng flite chỉ dùng để kiểm thử với tiếng Anh.")
    source = scratch / "speech.txt"
    audio = scratch / "voice.wav"

    def speak(phrase, target):
        source.write_text(phrase, encoding="utf-8")
        if engine == "espeak":
            command = ["espeak-ng", "-v", language, "-s", "155", "-f", source.name, "-w", target.name]
        else:
            command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                       "flite=textfile=speech.txt:voice=slt", target.name]
        subprocess.run(command, cwd=scratch, check=True)

    speak(text, audio)
    duration = audio_duration(audio)
    # The offline engines do not expose timestamps through this CLI. Keep a
    # single take, and estimate caption lengths with separate timing probes.
    spans = list(caption_spans(text))
    probe = scratch / "cue.wav"
    weights = []
    for first, last in spans:
        speak(text[first:last], probe)
        weights.append(audio_duration(probe))
    scale = duration / sum(weights)
    starts = [0.0] * len(text)
    ends = [0.0] * len(text)
    elapsed = 0.0
    for (first, last), weight in zip(spans, weights):
        step = weight * scale / (last - first)
        for index in range(first, last):
            starts[index] = elapsed + (index - first) * step
            ends[index] = starts[index] + step
        elapsed += weight * scale
    return audio, starts, ends
