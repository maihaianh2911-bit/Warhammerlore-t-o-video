"""The posting caption of a video: lore/<N>/caption.txt, published beside video.mp4 (owner, 16/11/2026).

Format (German, the channel's language; UTF-8; at most 2000 characters):
  line 1      a hook title of at most 80 characters, true to the script
  next lines  2–4 short sentences about the video
  blank line
  5–8 hashtags on one line (#Warhammer40k #40kLore #Warhammer #shorts + faction tags)
  blank line
  one picture-credit line starting with "Bildquellen:"

Usage: python3 -m factory.caption lore/<N>/caption.txt   (prints every problem; exit 1 when there is one)
"""
import re
import sys
import unicodedata
from pathlib import Path

from .script import sentence_end

MAX_CHARS = 2000
MAX_TITLE = 80
HASHTAGS = (5, 8)
SENTENCES = (2, 4)
# marks German never uses, checked after splitting letters from their marks (NFD): Vietnamese d with stroke,
# circumflex (a e o with a hat, also under a tone mark), breve, horn, dot below, hook above; and Japanese / Chinese
FOREIGN = re.compile("[\u0111\u0110\u0302\u0306\u031b\u0323\u0309\u3040-\u30ff\u4e00-\u9fff]")


def problems(text):
    """Every way caption.txt breaks the format, in Vietnamese for the owner and Claude; [] when it is right."""
    found = []
    text = text.replace("\r\n", "\n").strip("\n")
    if len(text) > MAX_CHARS:
        found.append(f"dài {len(text)} ký tự, tối đa {MAX_CHARS}")
    if FOREIGN.search(unicodedata.normalize("NFD", text)):
        found.append("có chữ không phải tiếng Đức (caption phải viết bằng tiếng Đức, ngôn ngữ của kênh)")
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if len(blocks) != 3:
        return found + ["cần đúng 3 đoạn cách nhau bằng một dòng trống: tiêu đề + câu, hashtag, Bildquellen"]
    head, tags, credits = blocks
    title, *body = head.split("\n")
    if not title.strip() or title.lstrip().startswith("#"):
        found.append("dòng 1 phải là tiêu đề")
    elif len(title.strip()) > MAX_TITLE:
        found.append(f"tiêu đề dài {len(title.strip())} ký tự, tối đa {MAX_TITLE}")
    sentences = sum(sentence_end(word) for word in " ".join(body).split())
    if not SENTENCES[0] <= sentences <= SENTENCES[1]:
        found.append(f"sau tiêu đề cần {SENTENCES[0]}–{SENTENCES[1]} câu ngắn (đang có {sentences})")
    words = tags.split()
    if any(not re.fullmatch(r"#\w+", word) for word in words):
        found.append("đoạn 2 chỉ gồm hashtag dạng #Wort, cách nhau bằng dấu cách")
    elif not HASHTAGS[0] <= len(words) <= HASHTAGS[1]:
        found.append(f"cần {HASHTAGS[0]}–{HASHTAGS[1]} hashtag (đang có {len(words)})")
    elif len({word.lower() for word in words}) != len(words):
        found.append("có hashtag bị lặp")
    if not credits.startswith("Bildquellen:") or "\n" in credits:
        found.append("đoạn cuối là một dòng bắt đầu bằng \"Bildquellen:\"")
    return found


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    try:
        found = problems(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        found = [f"không đọc được ({error})"]
    for problem in found:
        print(f"{path}: {problem}")
    if found:
        raise SystemExit(1)
    print(f"{path}: đúng định dạng")


if __name__ == "__main__":
    main()
