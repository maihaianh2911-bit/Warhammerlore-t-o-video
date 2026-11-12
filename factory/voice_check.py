import re
import unicodedata
from difflib import SequenceMatcher


def token(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFC", text).casefold())


def load_model():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("Cần cài requirements-voice.txt để nghe lại giọng VN11.") from None
    return WhisperModel("small", device="cpu", compute_type="int8")


def transcribe(model, audio, language):
    segments, _ = model.transcribe(str(audio), language=language, word_timestamps=True, vad_filter=True)
    return [(word.word.strip(), word.start, word.end) for segment in segments for word in segment.words or []
            if token(word.word)]


def align_words(text, heard, duration):
    words = list(re.finditer(r"\S+", text))
    heard = [(word, max(0.0, min(start, duration)), max(0.0, min(end, duration)))
             for word, start, end in heard]
    if not words or not heard:
        raise ValueError("Whisper không tìm được lời đọc để căn phụ đề.")
    comparison = SequenceMatcher(None, [token(word.group()) for word in words],
                                 [token(word) for word, _, _ in heard], autojunk=False)
    score = comparison.ratio()
    if score < 0.55:
        raise ValueError(f"Giọng đọc khớp {score:.0%} với kịch bản. Kiểm tra ngôn ngữ và mã giọng VN11.")
    timings = []
    flagged = []
    for operation, first, last, heard_first, heard_last in comparison.get_opcodes():
        if operation == "equal":
            timings.extend((start, end) for _, start, end in heard[heard_first:heard_last])
            continue
        if heard_first < heard_last:
            start, end = heard[heard_first][1], heard[heard_last - 1][2]
        else:
            start = heard[heard_first - 1][2] if heard_first else 0.0
            end = heard[heard_first][1] if heard_first < len(heard) else duration
        end = max(start, end)
        flagged.append({
            "start": round(start, 3), "end": round(end, 3),
            "script": " ".join(word.group() for word in words[first:last]),
            "heard": " ".join(word for word, _, _ in heard[heard_first:heard_last]),
        })
        if last > first:
            step = (end - start) / (last - first)
            timings.extend((start + step * i, start + step * (i + 1)) for i in range(last - first))

    starts = [0.0] * len(text)
    ends = [0.0] * len(text)
    for word, (start, end) in zip(words, timings):
        step = max(0.0, end - start) / len(word.group())
        for offset, index in enumerate(range(word.start(), word.end())):
            starts[index] = start + step * offset
            ends[index] = start + step * (offset + 1)
    return starts, ends, {"match": round(score, 3), "review": flagged}
