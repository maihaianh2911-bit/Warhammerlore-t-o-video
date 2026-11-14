"""The catalogue of named edits ("bảng cách edit"): what a shot of picks.json gets from `"edit": "<name>"`.

An edit bundles the camera fields the renderer already has (move, pace, kick, sometimes zoom) under a name the
owner can say ("cảnh 5 đổi sang kiểu lao-toi"). It is chosen by the meaning of the line the shot carries; the
analysis of the owner's sample that the catalogue is built on is 00-video-mau/HUONG-DAN-EDIT.md, the table Claude
chooses from is in AGENT.md. A field written in the shot itself always wins over the edit's value, and a shot
without `edit` is left exactly as written.
"""

# name: (Vietnamese label, the fields it sets, what the viewer sees, when to use it)
EDITS = {
    "ap-mat": ("áp mặt", {"move": "push", "pace": "even", "kick": 0.03, "zoom": 1.3},
               "đẩy chậm, đều vào khuôn mặt",
               "câu nói ai đó là ai, nhân vật được gọi tên hoặc đang nói"),
    "de-doa": ("đe dọa", {"move": "push", "pace": "surge", "kick": 0, "zoom": 1.45},
               "đẩy rất gần vào mặt, càng về cuối càng nhanh",
               "lời đe dọa, lời thú nhận, cái chết, câu lạnh người"),
    "toan-canh": ("toàn cảnh", {"move": "push", "pace": "even", "kick": 0, "zoom": 1.18},
                  "mở rộng cả cảnh rồi tiến rất chậm tới nhân vật chính, vẫn thấy bối cảnh",
                  "câu giới thiệu nơi chốn, đạo quân, hạm đội, hai nhân vật gặp nhau"),
    "qua-vat": ("lướt qua vật", {"move": "rise", "pace": "settle", "kick": 0.03},
                "bắt đầu ở vũ khí, huy hiệu, vết thương rồi đi lên khuôn mặt (đặt from ở đúng vật đó)",
                "câu nhắc tới vũ khí, huy hiệu, bộ giáp, vết thương của nhân vật"),
    "lao-toi": ("lao tới", {"move": "glide", "pace": "surge", "kick": 0.08},
                "lướt ngang theo hướng nhân vật lao tới, tăng tốc vào chủ thể",
                "cuộc xung phong, cú tập kích, điều bất ngờ lộ ra"),
    "va-dap": ("va đập", {"move": "push", "pace": "settle", "kick": 0.12, "zoom": 1.35},
               "cảnh vào bằng một cú giật mạnh rồi lắng xuống",
               "câu có đòn đánh, tiếng nổ, sự phản bội, một cái tên vừa lộ"),
    "ngang-len": ("ngẩng lên", {"move": "rise", "pace": "even", "kick": 0.03},
                  "đi đều từ dưới chân lên đầu",
                  "nhân vật khổng lồ, tượng đài, ngọn tháp, chiến hạm dựng đứng"),
    "luot-ngang": ("lướt ngang", {"move": "glide", "pace": "even", "kick": 0},
                   "lướt đều dọc theo chiến tuyến hoặc đoàn quân tới chủ thể",
                   "trận đánh, hàng quân, hạm đội dàn ngang; câu kể diễn biến"),
    "giu-yen": ("giữ yên", {"move": "push", "pace": "even", "kick": 0, "zoom": 1.1},
                "gần như đứng yên, chỉ trôi nhẹ",
                "văn bản, ấn ký, bản đồ; câu giải thích lore cần người xem nhìn kỹ"),
    "lui-ra": ("lùi ra", {"move": "pull", "pace": "even", "kick": 0},
               "bắt đầu sát chủ thể rồi lùi ra cho thấy bối cảnh quanh nó",
               "nhảy thời gian (\"nhiều thế kỷ sau\"), hậu quả, câu kết của video"),
}


def edit_names():
    return ", ".join(EDITS)


def apply_edit(shot, number=None):
    """The shot with the fields of its edit filled in; fields the shot sets itself are kept."""
    if "edit" not in shot:
        return shot
    name = shot["edit"]
    if not isinstance(name, str) or name not in EDITS:
        where = f"Cảnh {number}: " if number else ""
        raise ValueError(f"{where}không có kiểu edit \"{name}\". Các kiểu có: {edit_names()}.")
    return {**EDITS[name][1], **shot}


def edit_label(shot):
    """How a shot's edit is shown to the owner: "de-doa (đe dọa)", or "tự chọn" for a hand-written camera path."""
    name = shot.get("edit")
    return f"{name} ({EDITS[name][0]})" if name in EDITS else "tự chọn"


def edits_table(shots, lines, seconds=None):
    """edits.md: one row per shot — number, the line it starts on, picture, edit, why — for the closing comment,
    so the owner can answer "cảnh 5 đổi sang kiểu lao-toi". lines: the script's lines; seconds: shot lengths."""
    def cell(text):
        return " ".join(str(text).split()).replace("|", "/")

    rows = ["# Cách edit từng cảnh", "",
            "Muốn đổi: bình luận \"cảnh <số> đổi sang kiểu <tên>\". Các kiểu: " + edit_names() + ".", "",
            "| Cảnh | Câu | Hình | Kiểu edit | Vì sao |", "|---|---|---|---|---|"]
    for number, shot in enumerate(shots, start=1):
        at = shot.get("at", 1)
        text = lines[int(at) - 1]
        words = text if len(text) <= 60 else text[:57].rsplit(" ", 1)[0] + "…"
        length = f" · {seconds[number - 1]:.0f}s" if seconds else ""
        rows.append(f"| {number}{length} | {at:g}. {cell(words)} | {cell(shot.get('img') or 'nền ' + shot['theme'])} "
                    f"| {edit_label(shot)} | {cell(shot.get('why') or '—')} |")
    return "\n".join(rows) + "\n"
