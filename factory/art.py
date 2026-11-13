import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


ART_ROOT = Path(__file__).resolve().parent.parent / "art"
LABEL_FONT = Path(__file__).resolve().parent.parent / "fonts" / "Montserrat-ExtraBold.ttf"
MAX_IMAGE_BYTES = 16 * 1024 * 1024

PALETTES = {
    "orbit": ((5, 11, 26), (21, 83, 137), (144, 220, 246)),
    "archive": ((17, 9, 9), (104, 52, 30), (240, 177, 119)),
    "rift": ((18, 6, 26), (108, 32, 114), (239, 144, 226)),
    "decay": ((13, 16, 6), (75, 103, 22), (198, 220, 109)),
    "inferno": ((22, 4, 6), (137, 26, 16), (255, 119, 73)),
}


def open_picture(path):
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError(f"Ảnh {path.name} vượt giới hạn 16 MB.")
    with Image.open(path) as image:
        if min(image.size) < 320 or image.width * image.height > 24_000_000:
            raise ValueError(f"Kích thước ảnh {path.name} ngoài phạm vi hỗ trợ.")
        return ImageOps.exif_transpose(image).convert("RGB")


def contact_sheet(tiles, path, columns=4):
    """Numbered overview of pictures: tiles = [(image, label)]."""
    if not tiles:
        return
    cell_w = max(image.width for image, _ in tiles) + 12
    cell_h = max(image.height for image, _ in tiles) + 30
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), (12, 12, 14))
    draw = ImageDraw.Draw(sheet)
    for index, (image, label) in enumerate(tiles):
        left, top = (index % columns) * cell_w, (index // columns) * cell_h
        draw.text((left + 6, top + 6), label, fill=(255, 210, 90), font=label_font(draw, label, cell_w - 12))
        sheet.paste(image, (left + 6, top + 26))
    sheet.save(path, quality=85)


def label_font(draw, label, width):
    """The repo's Montserrat (Pillow's built-in bitmap font drops the spaces: "1 L1 3sorbitstart"), as large as
    fits the tile."""
    try:
        for size in range(15, 8, -1):
            font = ImageFont.truetype(str(LABEL_FONT), size)
            if draw.textlength(label, font=font) <= width:
                break
        return font
    except OSError:
        return ImageFont.load_default()


def grade_frame(image):
    return ImageEnhance.Color(ImageEnhance.Contrast(image).enhance(1.06)).enhance(1.12)


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
    elif theme in ("archive", "decay"):
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


