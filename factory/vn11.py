import json
import os
import re
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


API_BASE = "https://11labs.id.vn/api/external/v1"
LANGUAGES = {"vi": "Vietnamese", "en": "English"}
POLL_SECONDS = 4
TRANSIENT = {429, 500, 502, 503, 504}
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(path, key, body=None, content_type=None):
    headers = {"x-api-key": key, "User-Agent": "warhammer-lore-video-factory/1.0"}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(f"{API_BASE}/{path}", data=body, headers=headers)
    try:
        with build_opener(NoRedirect()).open(request, timeout=40) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, {}


def create_job(text, language, key, voice):
    if voice.startswith("clone_"):
        boundary = uuid.uuid4().hex
        fields = {"text": text, "clone_voice_id": voice}
        body = "".join(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
            for name, value in fields.items()
        ) + f"--{boundary}--\r\n"
        path = "clone.php"
        content_type = f"multipart/form-data; boundary={boundary}"
    else:
        body = json.dumps({
            "text": text,
            "voice_id": voice,
            "voice_settings": {
                "language": LANGUAGES[language], "speed": 1.0,
                "normalization": False, "expressive_optimize": False,
            },
        }, ensure_ascii=False)
        path = "tts.php"
        content_type = "application/json"
    try:
        status, payload = request_json(path, key, body.encode("utf-8"), content_type)
    except (URLError, TimeoutError, ValueError):
        raise RuntimeError("VN11 chưa xác nhận tạo giọng. Kiểm tra lượt tạo bên VN11 trước khi chạy lại.") from None
    if status in (401, 403):
        raise RuntimeError(f"VN11 từ chối tạo giọng (HTTP {status}). Kiểm tra khóa và hạn mức.")
    job = payload.get("job_id") if isinstance(payload, dict) else None
    if not 200 <= status < 300 or not isinstance(job, (str, int)) or not job:
        raise RuntimeError(f"VN11 chưa cấp mã tạo giọng (HTTP {status}).")
    return job


def poll_job(job, key):
    deadline = time.monotonic() + 900
    path = "status.php?" + urlencode({"job_id": job})
    while time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        try:
            status, data = request_json(path, key)
        except (URLError, TimeoutError):
            continue
        if status in TRANSIENT:
            continue
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError(f"VN11 không trả trạng thái giọng (HTTP {status}).")
        state = data.get("status")
        if state == "completed":
            return data.get("download_url")
        if state == "failed":
            raise RuntimeError("VN11 báo lượt tạo giọng thất bại.")
    raise RuntimeError("VN11 chưa hoàn thành sau 15 phút. Kiểm tra lượt tạo trên VN11 trước khi chạy lại.")


def save_audio(url, path):
    if not isinstance(url, str) or urlsplit(url).scheme != "https":
        raise RuntimeError("VN11 chưa trả liên kết HTTPS cho tệp giọng.")
    try:
        with urlopen(Request(url, headers={"User-Agent": "warhammer-lore-video-factory/1.0"}), timeout=90) as response:
            if urlsplit(response.url).scheme != "https":
                raise RuntimeError("Liên kết tệp giọng phải dùng HTTPS.")
            audio = response.read(MAX_AUDIO_BYTES + 1)
    except (URLError, TimeoutError):
        raise RuntimeError("Không tải được tệp giọng từ VN11.") from None
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise RuntimeError("Kích thước tệp giọng VN11 ngoài giới hạn.")
    path.write_bytes(audio)


def configuration():
    key = os.environ.get("VN11_API_KEY", "")
    voice = os.environ.get("VN11_VOICE_ID", "")
    if not key or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", voice):
        raise ValueError("Cần secret VN11_API_KEY và biến VN11_VOICE_ID trong repo 40K.")
    return key, voice


def synthesize(text, language, scratch, key, voice):
    job = create_job(text, language, key, voice)
    audio = scratch / "voice.mp3"
    save_audio(poll_job(job, key), audio)
    return audio
