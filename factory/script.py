import json
import re
import textwrap
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Cue:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Job:
    title: str
    text: str
    spans: tuple      # (first, last) character positions of every line in text
    queries: tuple
    voice: str


MAX_NARRATION_CHARS = 10_000
THEMES = ("orbit", "archive", "rift", "decay", "inferno")


def clean(value):
    return " ".join(unicodedata.normalize("NFC", value).split()) if isinstance(value, str) else ""


def load_job(path: Path) -> Job:
    """script.json: {"title", "paragraphs": [[line, ...], ...], "queries": [...], "voice": "clone_611"}."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    title = clean(data.get("title"))
    paragraphs = data.get("paragraphs")
    if not title:
        raise ValueError("script.json thiếu title.")
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ValueError("script.json cần paragraphs là danh sách các đoạn.")
    text = ""
    spans = []
    for paragraph in paragraphs:
        if not isinstance(paragraph, list) or not paragraph:
            raise ValueError("Mỗi đoạn trong paragraphs là một danh sách câu.")
        for index, line in enumerate(paragraph):
            line = clean(line)
            if not line:
                raise ValueError(f"Câu số {len(spans) + 1} trong script.json đang trống.")
            if text:
                text += " " if index else "\n\n"
            spans.append((len(text), len(text) + len(line)))
            text += line
    if len(text) > MAX_NARRATION_CHARS:
        raise ValueError(f"Lời đọc dài {len(text):,} ký tự, vượt giới hạn {MAX_NARRATION_CHARS:,}.")
    queries = data.get("queries") or []
    if not isinstance(queries, list) or any(not clean(query) for query in queries):
        raise ValueError("queries trong script.json là danh sách từ khóa tìm ảnh.")
    voice = data.get("voice") or ""
    if not isinstance(voice, str) or (voice and not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", voice)):
        raise ValueError("voice trong script.json không hợp lệ.")
    return Job(title, text, tuple(spans), tuple(clean(query) for query in queries), voice)


def load_picks(path: Path, line_count):
    """picks.json: {"images": {name: {"src", "credit", "crop", "focal"}}, "shots": [{"at", "img" | "collage" | "theme"}]}."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    images = data.get("images") or {}
    shots = data.get("shots")
    if not isinstance(images, dict) or not isinstance(shots, list) or not shots:
        raise ValueError("picks.json cần images và danh sách shots.")
    for name, image in images.items():
        if not isinstance(image, dict) or not clean(image.get("src")) or not clean(image.get("credit")):
            raise ValueError(f"Ảnh {name} trong picks.json cần src và credit.")
    previous = 0
    for number, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            raise ValueError(f"Cảnh {number} trong picks.json sai định dạng.")
        at = shot.get("at", 1 if number == 1 else None)
        if not isinstance(at, (int, float)) or isinstance(at, bool) or not 1 <= at < line_count + 1:
            raise ValueError(f"Cảnh {number}: at phải là số câu từ 1 đến {line_count}.")
        if (number == 1 and at != 1) or at <= previous:
            raise ValueError(f"Cảnh {number}: cảnh đầu bắt đầu ở câu 1, các cảnh sau có at tăng dần.")
        previous = at
        names = [shot["img"]] if "img" in shot else shot.get("collage")
        if names is None:
            if shot.get("theme") not in THEMES:
                raise ValueError(f"Cảnh {number} cần img, collage hoặc theme ({', '.join(THEMES)}).")
        elif (not isinstance(names, list) or not names or ("collage" in shot and len(names) < 2)
              or any(name not in images for name in names)):
            raise ValueError(f"Cảnh {number} dùng ảnh chưa khai báo trong images.")
        for key in ("from", "to"):
            move = shot.get(key)
            if move is not None and not (isinstance(move, list) and len(move) == 3
                                         and 1 <= move[0] <= 1.8 and 0 <= move[1] <= 1 and 0 <= move[2] <= 1):
                raise ValueError(f"Cảnh {number}: {key} là [zoom 1–1.8, x 0–1, y 0–1].")
    return images, shots


def line_times(spans, starts, ends):
    return [(starts[first], max(ends[last - 1], starts[first])) for first, last in spans]


def shot_frames(shots, times, duration_frames, fps):
    """Frame ranges of the shots; `at` 13.5 cuts in the middle of line 13."""
    cuts = []
    for number, shot in enumerate(shots, start=1):
        at = shot.get("at", 1)
        start, end = times[int(at) - 1]
        frame = 0 if number == 1 else round((start + (at - int(at)) * (end - start)) * fps)
        if cuts and frame - cuts[-1] < fps // 2:
            raise ValueError(f"Cảnh {number - 1} ngắn hơn nửa giây. Đổi at của cảnh {number}.")
        cuts.append(frame)
    if duration_frames - cuts[-1] < fps // 2:
        raise ValueError("Cảnh cuối ngắn hơn nửa giây.")
    return list(zip(cuts, cuts[1:] + [duration_frames]))


def caption_spans(text: str):
    words = list(re.finditer(r"\S+", text))
    if not words:
        return
    first = 0
    for i, word in enumerate(words[:-1]):
        next_word = words[i + 1]
        length = word.end() - words[first].start()
        at_sentence = bool(re.search(r"""[.!?。！？]["'”’»)]*$""", word.group()))
        at_paragraph = "\n" in text[word.end():next_word.start()]
        next_length = next_word.end() - words[first].start()
        if at_paragraph or (at_sentence and length >= 18) or next_length > 54:
            yield words[first].start(), word.end()
            first = i + 1
    yield words[first].start(), words[-1].end()


def make_cues(text, starts, ends, duration):
    if len(starts) != len(text) or len(ends) != len(text):
        raise ValueError("Dấu thời gian không khớp với lời đọc.")
    spans = list(caption_spans(text))
    cues = []
    for i, (first, last) in enumerate(spans):
        start = max(starts[first], 0)
        next_start = starts[spans[i + 1][0]] if i + 1 < len(spans) else duration
        end = min(max(ends[last - 1], start + 0.5) + 0.12, next_start, duration)
        if end - start < 0.04:
            raise ValueError("Giọng đọc có mốc phụ đề quá ngắn hoặc sai thứ tự.")
        cue = Cue(" ".join(text[first:last].split()), start, end)
        cues.append(cue)
    return cues


def opening_frames(duration_frames, fps):
    return min(duration_frames, round(2.2 * fps))


def format_time(seconds, precision, decimal_separator, pad_hours):
    units_per_second = 10 ** precision
    total = round(seconds * units_per_second)
    whole, fraction = divmod(total, units_per_second)
    minutes, second = divmod(whole, 60)
    hour, minute = divmod(minutes, 60)
    hour_label = f"{hour:02d}" if pad_hours else str(hour)
    return f"{hour_label}:{minute:02d}:{second:02d}{decimal_separator}{fraction:0{precision}d}"


def caption_lines(text, width=29):
    lines = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    if len(lines) <= 2:
        return lines
    words = text.split()
    split = min(range(1, len(words)), key=lambda index: abs(
        len(" ".join(words[:index])) - len(" ".join(words[index:]))
    ))
    return [" ".join(words[:split]), " ".join(words[split:])]


def ass_text(lines):
    translate = str.maketrans({"\\": "＼", "{": "｛", "}": "｝"})
    return r"\N".join(line.translate(translate) for line in lines)


def write_subtitles(cues, srt: Path, ass: Path, hook, hook_end):
    blocks = []
    events = []
    for index, cue in enumerate(cues, start=1):
        lines = caption_lines(cue.text)
        srt_start = format_time(cue.start, 3, ",", True)
        srt_end = format_time(cue.end, 3, ",", True)
        blocks.append(f"{index}\n{srt_start} --> {srt_end}\n" + "\n".join(lines))
        ass_start = format_time(cue.start, 2, ".", False)
        ass_end = format_time(cue.end, 2, ".", False)
        events.append(f"Dialogue: 0,{ass_start},{ass_end},Default,,0,0,0,," + ass_text(lines))
    hook_text = textwrap.shorten(" ".join(hook.split()), width=63, placeholder="…")
    hook_time = format_time(hook_end, 2, ".", False)
    events.append(f"Dialogue: 1,0:00:00.00,{hook_time},Hook,,0,0,0,," + ass_text(caption_lines(hook_text, 31)))
    srt.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    ass.write_text(
        """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,DejaVu Sans,58,&H00FFFFFF,&H00000000,&H00080707,&H70080707,-1,0,0,0,81,100,0,0,1,5.4,1.5,2,105,105,317,1
Style: Hook,DejaVu Sans,76,&H003031FF,&H00000000,&H00080C16,&H80080C16,-1,-1,0,0,81,100,0,0,1,5.5,2,5,86,86,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
""" + "\n".join(events) + "\n",
        encoding="utf-8",
    )
