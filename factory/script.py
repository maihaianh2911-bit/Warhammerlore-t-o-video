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
MOVES = ("push", "rise", "from-left", "pull", "from-right", "fall", "glide")


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
    """picks.json: {"images": {name: {"src", "credit", "crop"}}, "shots": [{"at", "img" | "theme", "focus", "move", "zoom"}]}."""
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
        if "img" in shot:
            if shot["img"] not in images:
                raise ValueError(f"Cảnh {number} dùng ảnh chưa khai báo trong images.")
        elif shot.get("theme") not in THEMES:
            raise ValueError(f"Cảnh {number} cần img hoặc theme ({', '.join(THEMES)}).")
        focus = shot.get("focus")
        if focus is not None and not (isinstance(focus, list) and len(focus) == 2 and all(0 <= v <= 1 for v in focus)):
            raise ValueError(f"Cảnh {number}: focus là [x, y] trong khoảng 0–1.")
        zoom = shot.get("zoom")
        if zoom is not None and not (isinstance(zoom, (int, float)) and 1 <= zoom <= 2.3):
            raise ValueError(f"Cảnh {number}: zoom từ 1 đến 2.3.")
        if shot.get("move") not in (None, *MOVES):
            raise ValueError(f"Cảnh {number}: move là một trong {', '.join(MOVES)}.")
        start = shot.get("from")
        if start is not None and not (isinstance(start, list) and len(start) == 3
                                      and 1 <= start[0] <= 2.3 and 0 <= start[1] <= 1 and 0 <= start[2] <= 1):
            raise ValueError(f"Cảnh {number}: from là [zoom 1–2.3, x 0–1, y 0–1].")
        if "to" in shot:
            raise ValueError(f"Cảnh {number}: không đặt to; cảnh luôn kết thúc ở focus (trọng tâm nhân vật).")
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
    return r"\N".join(ass_escape(line) for line in lines)


def ass_escape(text):
    return text.translate(str.maketrans({"\\": "＼", "{": "｛", "}": "｝"}))


CHUNK_WORDS = 3
CHUNK_CHARS = 16
GOLD = "&H3FD2FF&"      # ASS colours are BGR
WHITE = "&HFFFFFF&"


def caption_chunks(text, starts, ends, duration):
    """Short groups of words (as the voice says them): [[(word, start, end), ...], ...], broken at punctuation."""
    chunks = [[]]
    words = list(re.finditer(r"\S+", text))
    for index, word in enumerate(words):
        start = min(max(starts[word.start()], 0), duration)
        end = min(max(ends[word.end() - 1], start), duration)
        chunk = chunks[-1]
        length = sum(len(item[0]) + 1 for item in chunk) + len(word.group())
        if chunk and (len(chunk) >= CHUNK_WORDS or length > CHUNK_CHARS):
            chunks.append(chunk := [])
        chunk.append((word.group(), start, end))
        following = text[word.end():words[index + 1].start()] if index + 1 < len(words) else ""
        if re.search(r"""[.!?…,;:–—]["'”’»)]*$""", word.group()) or "\n" in following:
            chunks.append([])
    return [chunk for chunk in chunks if chunk]


def chunk_events(chunks, duration):
    """One subtitle event per spoken word: the chunk stays, the word being said turns gold."""
    events = []
    for number, chunk in enumerate(chunks):
        following = chunks[number + 1][0][1] if number + 1 < len(chunks) else duration
        last = min(chunk[-1][2] + 0.35, following)      # the caption leaves during a pause
        for index, (_, start, _) in enumerate(chunk):
            end = chunk[index + 1][1] if index + 1 < len(chunk) else last
            if end - start < 0.02:
                continue
            words = [f"{{\\c{GOLD}}}{ass_escape(word)}{{\\c{WHITE}}}" if position == index else ass_escape(word)
                     for position, (word, _, _) in enumerate(chunk)]
            size = round(100 * min(1, (CHUNK_CHARS + 2) / len(" ".join(word for word, _, _ in chunk))))
            small = round(size * 0.86)      # a long word is narrowed to fit; every chunk pops in once
            look = (rf"{{\fscx{small}\fscy{small}\t(0,90,\fscx{size}\fscy{size})}}" if index == 0
                    else rf"{{\fscx{size}\fscy{size}}}")
            events.append((start, end, look + " ".join(words)))
    return events


def write_subtitles(cues, chunks, duration, srt: Path, ass: Path, hook, hook_end):
    blocks = []
    for index, cue in enumerate(cues, start=1):
        srt_start = format_time(cue.start, 3, ",", True)
        srt_end = format_time(cue.end, 3, ",", True)
        blocks.append(f"{index}\n{srt_start} --> {srt_end}\n" + "\n".join(caption_lines(cue.text)))
    events = [f"Dialogue: 0,{format_time(start, 2, '.', False)},{format_time(end, 2, '.', False)},Default,,0,0,0,,{text}"
              for start, end, text in chunk_events(chunks, duration)]
    hook_text = textwrap.shorten(" ".join(hook.split()), width=66, placeholder="…")
    hook_time = format_time(hook_end, 2, ".", False)
    fade = r"{\fad(180,260)}"
    events.append(f"Dialogue: 1,0:00:00.00,{hook_time},Hook,,0,0,0,,{fade}" + ass_text(caption_lines(hook_text, 18)))
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
Style: Default,Montserrat Thin ExtraBold,92,&H00FFFFFF,&H00000000,&H00060404,&HA0000000,0,0,0,0,100,100,0.5,0,1,7,3,8,60,60,1170,1
Style: Hook,Cinzel Black,76,&H0048C8FF,&H00000000,&H00050818,&HB0000000,0,0,0,0,100,100,1.5,0,1,6,4,8,70,70,250,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
""" + "\n".join(events) + "\n",
        encoding="utf-8",
    )
