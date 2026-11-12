import io
import json
import math
import random
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps


ART_ROOT = Path(__file__).resolve().parent.parent / "art"
CATALOG_PATH = ART_ROOT / "catalog.json"
MAX_IMAGE_BYTES = 16 * 1024 * 1024

PALETTES = {
    "orbit": ((6, 14, 21), (29, 72, 79), (146, 198, 186)),
    "archive": ((14, 13, 19), (77, 46, 41), (214, 153, 119)),
    "rift": ((14, 9, 24), (66, 33, 81), (198, 142, 205)),
}


def matches(text, term):
    return re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text.casefold()) is not None


def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def choose_art(catalog, text, previous, index):
    terms = [
        subject for subject in catalog["subjects"]
        if any(matches(text, term) for term in [subject["name"], *subject.get("aliases", [])])
    ]
    theme = terms[0]["theme"] if terms else ["orbit", "archive", "rift"][index % 3]
    references = []
    for subject in terms:
        references.append({
            "subject": subject["name"],
            "url": subject.get("gallery") or gallery_search(subject["name"]),
        })
    if not references:
        references.append({"subject": "Tìm theo lời đọc", "url": gallery_search(text[:110])})

    candidates = []
    for asset in catalog["assets"]:
        score = sum(matches(text, term) for term in asset["keywords"])
        # Optional qualifiers distinguish, for example, 30K and 40K depictions.
        required = asset.get("require_any", [])
        if score and (not required or any(matches(text, term) for term in required)):
            candidates.append((score, asset["source"] != previous, asset["source"], asset))
    candidates.sort(key=lambda item: (-item[0], not item[1], item[2]))
    return theme, references, [asset for _, _, _, asset in candidates]


def gallery_search(query):
    return "https://40k.gallery/?" + urlencode({"s": query})


def read_picture(asset):
    for key in ("title", "artist", "source", "rights"):
        if not isinstance(asset.get(key), str) or not asset[key].strip():
            raise ValueError(f"Mục ảnh thiếu {key}.")
    if urlsplit(asset["source"]).scheme != "https":
        raise ValueError("Nguồn ghi công của ảnh phải là liên kết HTTPS.")

    if "file" in asset:
        root = ART_ROOT.resolve()
        path = (root / asset["file"]).resolve()
        if not path.is_relative_to(root) or path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("Tệp ảnh nằm ngoài thư mục art hoặc quá lớn.")
        data = path.read_bytes()
    else:
        url = asset["url"]
        if urlsplit(url).scheme != "https":
            raise ValueError("URL ảnh phải dùng HTTPS.")
        request = Request(url, headers={"User-Agent": "WarhammerLoreVideoFactory/1.0"})
        with urlopen(request, timeout=12) as response:
            if urlsplit(response.url).scheme != "https":
                raise ValueError("Ảnh chuyển hướng sang URL không an toàn.")
            data = response.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Ảnh vượt giới hạn 16 MB.")
    with Image.open(io.BytesIO(data)) as image:
        if min(image.size) < 320 or image.width * image.height > 24_000_000:
            raise ValueError("Kích thước ảnh ngoài phạm vi hỗ trợ.")
        return ImageOps.exif_transpose(image).convert("RGB")


def fit_picture(image, size, focal=(0.5, 0.42)):
    width, height = size
    if image.width / image.height < 0.8:
        return ImageOps.fit(image, size, Image.Resampling.LANCZOS, centering=focal)
    backdrop = ImageOps.fit(image, size, Image.Resampling.LANCZOS, centering=focal)
    backdrop = Image.blend(backdrop.filter(ImageFilter.GaussianBlur(width / 18)), Image.new("RGB", size), 0.68)
    foreground = ImageOps.contain(image, (int(width * 0.96), int(height * 0.66)), Image.Resampling.LANCZOS)
    x = (width - foreground.width) // 2
    y = int(height * 0.43 - foreground.height / 2)
    backdrop.paste(foreground, (x, y))
    return backdrop


def atmosphere(size, theme, seed):
    width, height = size
    dark, glow, light = PALETTES[theme]
    rng = random.Random(seed)
    small = (180, 320)
    sw, sh = small
    center_x, center_y = 0.52 + rng.uniform(-0.13, 0.13), rng.uniform(0.34, 0.47)
    haze = Image.new("L", small)
    values = []
    for y in range(sh):
        for x in range(sw):
            distance = ((x / sw - center_x) * 1.9) ** 2 + ((y / sh - center_y) * 1.5) ** 2
            waves = math.sin(x * 0.09 + y * 0.12) * math.sin(y * 0.10 - x * 0.14)
            value = 200 * math.exp(-distance * 4) * (0.83 + 0.17 * waves) + rng.randrange(18)
            values.append(round(value))
    haze.putdata(values)
    image = ImageOps.colorize(haze, dark, glow).resize(size, Image.Resampling.BICUBIC)
    draw = ImageDraw.Draw(image)
    for _ in range(375):
        x, y = rng.randrange(width), rng.randrange(int(height * 0.84))
        strength = rng.uniform(0.12, 0.64)
        base = image.getpixel((x, y))
        tone = tuple(round(a + (b - a) * strength) for a, b in zip(base, light))
        radius = rng.choices([0, 1, 2], [65, 32, 3])[0] * width / 720
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=tone)

    x, y = round(center_x * width), round(center_y * height)
    radius = round(width * 0.32)
    if theme == "orbit":
        paint_orbit(image, x, y, radius, dark, glow, light, seed)
    elif theme == "archive":
        paint_archive(image, x, y, radius, dark, glow, light)
    else:
        paint_rift(image, x, y, radius, light, rng)
    return image


def paint_orbit(image, x, y, radius, dark, glow, light, seed):
    size = image.size
    rim = Image.new("RGBA", size)
    arc = ImageDraw.Draw(rim)
    circle = (x - radius, y - radius, x + radius, y + radius)
    arc.arc(circle, 163, 310, fill=(*light, 210), width=max(3, radius // 24))
    bloom = rim.filter(ImageFilter.GaussianBlur(radius / 9))
    image.paste(bloom, (0, 0), bloom)

    texture_size = (256, 256)
    rng = random.Random(seed)
    texture = Image.new("RGB", texture_size)
    pixels = []
    for py in range(256):
        for px in range(256):
            cloud = math.sin(py * 0.21 + 4 * math.sin(px / 36)) * 0.15
            lightness = max(0.0, min(1.0, 0.65 - (px + py) / 650 + cloud + rng.random() * 0.09))
            pixels.append(tuple(round(a + (b - a) * lightness) for a, b in zip(dark, glow)))
    texture.putdata(pixels)
    planet_size = (2 * radius, 2 * radius)
    mask = Image.new("L", planet_size)
    ImageDraw.Draw(mask).ellipse((0, 0, planet_size[0] - 1, planet_size[1] - 1), fill=255)
    image.paste(texture.resize(planet_size, Image.Resampling.BICUBIC), (x - radius, y - radius), mask)
    draw = ImageDraw.Draw(image)
    draw.arc(circle, 168, 306, fill=light, width=max(1, radius // 105))
    for delta, start, end in ((1.24, 190, 280), (1.38, 15, 150), (1.56, 310, 353)):
        orbit = (x - radius * delta, y - radius * delta, x + radius * delta, y + radius * delta)
        draw.arc(orbit, start, end, fill=glow, width=max(1, radius // 140))
    for angle in (37, 219):
        point = (x + radius * 1.38 * math.cos(math.radians(angle)),
                 y + radius * 1.38 * math.sin(math.radians(angle)))
        px, py = point
        draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=light)


def paint_archive(image, x, y, radius, dark, glow, light):
    draw = ImageDraw.Draw(image)
    for shift in (-1.18, -0.70, 0, 0.70, 1.18):
        cx = x + shift * radius
        half = radius * (0.30 if shift == 0 else 0.23)
        top = y - radius * (1.45 - abs(shift) * 0.64)
        bottom = y + radius * 1.7
        silhouette = [(cx - half, bottom), (cx - half, top + half * 1.7),
                      (cx, top), (cx + half, top + half * 1.7), (cx + half, bottom)]
        draw.polygon(silhouette, fill=dark)
        draw.line(silhouette[:3], fill=glow, width=2)
        draw.line((cx, top + half * 2, cx, bottom - half), fill=glow, width=1)
        for offset in (1.9, 2.6, 3.3):
            dot_y = top + half * offset
            draw.line((cx - half * 0.33, dot_y, cx + half * 0.33, dot_y), fill=light, width=1)


def paint_rift(image, x, y, radius, light, rng):
    veil = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(veil)
    points = []
    for i in range(23):
        factor = (i - 11) / 11
        points.append((x + factor * radius * 1.7, y - factor * radius + rng.uniform(-0.24, 0.24) * radius))
    draw.line(points, fill=(*light, 200), width=max(5, radius // 14))
    bloom = veil.filter(ImageFilter.GaussianBlur(radius / 7))
    image.paste(bloom, (0, 0), bloom)
    core = ImageDraw.Draw(image)
    core.line(points, fill=light, width=max(1, radius // 100))
    for point in points[3::4]:
        px, py = point
        tail = (px + rng.uniform(-0.27, 0.27) * radius, py + radius * 0.40)
        core.line([point, ((px + tail[0]) / 2 + 8, (py + tail[1]) / 2), tail], fill=light, width=1)


def title_font(size):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
    return ImageFont.truetype(path, size)


def dress_frame(image, title):
    width, height = image.size
    gradient = Image.new("L", (1, height))
    gradient.putdata([round(max(0.36 * (1 - y / (height * 0.32)), 0.91 * ((y / height) ** 3.8)) * 255)
                      for y in range(height)])
    image.paste((4, 8, 13), (0, 0), gradient.resize(image.size))
    if not title:
        return
    draw = ImageDraw.Draw(image)
    left = round(width * 0.10)
    y = round(height * 0.54)
    font = title_font(round(width * 0.074))
    lines = [""]
    for word in title.split():
        candidate = f"{lines[-1]} {word}".strip()
        if lines[-1] and draw.textlength(candidate, font=font) > width * 0.80:
            lines.append(word)
        else:
            lines[-1] = candidate
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1].rstrip("…") + "…"
    draw.line((left, y - width * 0.037, left + width * 0.12, y - width * 0.037), fill=(142, 187, 176), width=2)
    for line in lines:
        while line and draw.textlength(line, font=font) > width * 0.80:
            line = line[:-2] + "…" if len(line) > 2 else ""
        draw.text((left, y), line, fill=(239, 234, 225), font=font, stroke_width=1, stroke_fill=(6, 11, 17))
        y += round(width * 0.09)
