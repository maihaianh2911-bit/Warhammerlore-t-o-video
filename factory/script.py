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
class Shot:
    text: str
    start_frame: int
    end_frame: int


def read_script(path: Path) -> str:
    text = unicodedata.normalize("NFC", path.read_text(encoding="utf-8-sig"))
    # Keep paragraph breaks for the voice, and join lines wrapped by the author.
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", text)]
    text = "\n\n".join(part for part in paragraphs if part)
    if not text or len(text) > 6000:
        raise ValueError("Kịch bản cần có từ 1 đến 6.000 ký tự.")
    return text


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
        if at_paragraph or (at_sentence and length >= 24) or next_length > 62:
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


def make_shots(cues, duration_frames, fps):
    cuts = [(0, 0)]
    for i, cue in enumerate(cues[1:], start=1):
        frame = round(cue.start * fps)
        if frame - cuts[-1][0] >= 4 * fps and duration_frames - frame >= 2 * fps:
            cuts.append((frame, i))
    cuts.append((duration_frames, len(cues)))
    return [
        Shot(" ".join(cue.text for cue in cues[first:last]), start_frame, end_frame)
        for (start_frame, first), (end_frame, last) in zip(cuts, cuts[1:])
    ]


def format_time(seconds, precision, decimal_separator, pad_hours):
    units_per_second = 10 ** precision
    total = round(seconds * units_per_second)
    whole, fraction = divmod(total, units_per_second)
    minutes, second = divmod(whole, 60)
    hour, minute = divmod(minutes, 60)
    hour_label = f"{hour:02d}" if pad_hours else str(hour)
    return f"{hour_label}:{minute:02d}:{second:02d}{decimal_separator}{fraction:0{precision}d}"


def caption_lines(text):
    return textwrap.wrap(text, width=35, break_long_words=False, break_on_hyphens=False)


def write_subtitles(cues, srt: Path, ass: Path):
    blocks = []
    events = []
    for index, cue in enumerate(cues, start=1):
        lines = caption_lines(cue.text)
        srt_start = format_time(cue.start, 3, ",", True)
        srt_end = format_time(cue.end, 3, ",", True)
        blocks.append(f"{index}\n{srt_start} --> {srt_end}\n" + "\n".join(lines))
        ass_start = format_time(cue.start, 2, ".", False)
        ass_end = format_time(cue.end, 2, ".", False)
        clean = (line.translate(str.maketrans({"\\": "＼", "{": "｛", "}": "｝"})) for line in lines)
        events.append(f"Dialogue: 0,{ass_start},{ass_end},Default,,0,0,0,," + r"\N".join(clean))
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
Style: Default,DejaVu Sans,48,&H00F0EAE2,&H00000000,&H00201811,&H80201811,-1,0,0,0,100,100,0,0,1,3,2,2,92,92,330,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
""" + "\n".join(events) + "\n",
        encoding="utf-8",
    )
