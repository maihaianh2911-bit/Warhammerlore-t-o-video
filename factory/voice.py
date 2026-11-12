import subprocess
from pathlib import Path


def audio_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    duration = float(result.stdout)
    if not 0 < duration <= 600:
        raise ValueError("Độ dài giọng đọc nằm ngoài giới hạn dựng của bản hiện tại.")
    return duration
