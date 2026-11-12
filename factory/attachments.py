"""Pictures the owner attached to the issue (dragged into the issue text or a comment).

40K Gallery blocks automated requests, so the owner saves pictures in a browser and attaches them; this step
copies them to <out>/<n>.jpg with index.json (where each came from) and a numbered sheet.jpg for Claude to choose.
"""
import io
import json
import re
from urllib.error import URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

from .art import MAX_IMAGE_BYTES, contact_sheet

ATTACHMENT = re.compile(
    r"https://(?:github\.com/user-attachments/assets/[0-9a-f-]{36}"
    r"|user-images\.githubusercontent\.com/\d+/[\w.-]+\.(?:png|jpe?g|webp))"
)
MAX_PICTURES = 60


def attachment_urls(texts):
    urls = []
    for text in texts:
        for url in ATTACHMENT.findall(text or ""):
            if url not in urls:
                urls.append(url)
    return urls[:MAX_PICTURES]


def owner_texts(issue, comments, owner):
    """Issue text and comments written by the repo owner; other people's attachments are ignored."""
    entries = [issue, *comments]
    return [entry.get("body") or "" for entry in entries
            if ((entry.get("user") or {}).get("login") or "").casefold() == owner.casefold()]


def download(urls, out):
    out.mkdir(parents=True, exist_ok=True)
    index = []
    tiles = []
    for url in urls:
        try:
            with urlopen(Request(url, headers={"User-Agent": "LoreVideoFactory/1.0"}), timeout=60) as response:
                data = response.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError("quá 16 MB")
            with Image.open(io.BytesIO(data)) as image:
                picture = ImageOps.exif_transpose(image).convert("RGB")
        except (OSError, URLError, ValueError) as error:   # videos and other files are simply not pictures
            index.append({"url": url, "skipped": str(error)[:120]})
            continue
        number = len(tiles) + 1
        width, height = picture.size
        picture.thumbnail((4000, 4000))
        picture.save(out / f"{number}.jpg", quality=92)
        index.append({"file": f"{number}.jpg", "url": url, "width": width, "height": height})
        tile = picture.copy()
        tile.thumbnail((360, 360))
        tiles.append((tile, f"#{number}  {width}x{height}"))
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    contact_sheet(tiles, out / "sheet.jpg")
    return len(tiles)
