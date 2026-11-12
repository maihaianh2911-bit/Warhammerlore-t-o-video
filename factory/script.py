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


def read_script(path: Path, max_chars=6000) -> str:
    text = unicodedata.normalize("NFC", path.read_text(encoding="utf-8-sig"))
    # Keep paragraph breaks for the voice, and join lines wrapped by the author.
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", text)]
    text = "\n\n".join(part for part in paragraphs if part)
    if not text or len(text) > max_chars:
        raise ValueError(f"Kịch bản cần có từ 1 đến {max_chars:,} ký tự.")
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


def make_shots(cues, duration_frames, fps, subjects=lambda text: set()):
    cuts = [0]
    hook = opening_frames(duration_frames, fps)
    if duration_frames - hook >= 2 * fps:
        cuts.append(hook)
    focus = subjects(cues[0].text)
    for cue in cues[1:]:
        frame = round(cue.start * fps)
        if frame < cuts[-1]:
            focus = subjects(cue.text) or focus
            continue
        names = subjects(cue.text)
        new_subject = bool(names - focus)
        minimum = 2.8 if new_subject else 4.5
        if frame - cuts[-1] >= minimum * fps and duration_frames - frame >= 2 * fps:
            cuts.append(frame)
        focus = names or focus
    cuts.append(duration_frames)
    return [
        Shot(
            " ".join(cue.text for cue in cues if round(cue.start * fps) < end
                     and round(cue.end * fps) > start),
            start,
            end,
        )
        for start, end in zip(cuts, cuts[1:])
    ]


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
