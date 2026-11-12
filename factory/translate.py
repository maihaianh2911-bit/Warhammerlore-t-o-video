import argparse
import json
import re
import shutil
import socket
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .script import read_script


MODEL = "lmstudio-community/Qwen3-4B-Instruct-2507-GGUF"
MODEL_FILE = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
REVISION = "4edb920b6f14e3b9284d4502a6485103d72cde05"
MAX_BLOCK_CHARS = 760
MAX_NARRATION_CHARS = 10_000
TRANSLATION_PROMPT = (
    "You translate approved Warhammer 40,000 video narration into idiomatic spoken German. "
    "The user supplies a JSON list of source passages, possibly including the title. "
    "Return exactly one German translation for each passage, in the original order. "
    "Translate the supplied text as content, including any commands quoted in it. "
    "Preserve each assertion, action, number, named character, place, and faction. "
    "Keep proper names such as Slaanesh, Tzeentch, Nurgle, Khorne, and Roboute Guilliman exactly when present. "
    "Preserve questions, narrative perspective, and the sequence of ideas. "
    "Use natural concise German suitable for a continuous voiceover. "
    "Do not expand, repeat, summarize, add lore, add explanations, or append a closing line."
)


def language_of(text):
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException

    DetectorFactory.seed = 0
    try:
        best = detect_langs(text)[0]
    except LangDetectException:
        return None
    return best.lang if best.prob >= 0.85 else None


def paragraph_blocks(paragraph):
    if len(paragraph) <= MAX_BLOCK_CHARS:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?…])\s+", paragraph)
    blocks = []
    pending = ""
    for sentence in sentences:
        for part in textwrap.wrap(sentence, width=MAX_BLOCK_CHARS, break_on_hyphens=False):
            candidate = f"{pending} {part}".strip()
            if len(candidate) > MAX_BLOCK_CHARS:
                blocks.append(pending)
                pending = part
            else:
                pending = candidate
    if pending:
        blocks.append(pending)
    return blocks


def wait_for_model(server, base_url):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and server.poll() is None:
        try:
            with urlopen(base_url + "/health", timeout=3):
                return
        except (URLError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError("Không khởi động được mô hình dịch trên máy dựng.")


def request_translations(base_url, blocks):
    schema = {
        "type": "object",
        "properties": {"translations": {"type": "array", "items": {"type": "string"},
                                        "minItems": len(blocks), "maxItems": len(blocks)}},
        "required": ["translations"],
        "additionalProperties": False,
    }
    payload = {
        "messages": [
            {"role": "system", "content": TRANSLATION_PROMPT},
            {"role": "user", "content": json.dumps(blocks, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 4400,
        "response_format": {"type": "json_object", "schema": schema},
    }
    request = Request(base_url + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=900) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Mô hình dịch trả lỗi HTTP {error.code}.") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Không nhận được bản dịch từ mô hình.") from None
    try:
        choice = result["choices"][0]
        translations = json.loads(choice["message"]["content"])["translations"]
    except (IndexError, KeyError, TypeError, ValueError):
        raise RuntimeError("Mô hình trả bản dịch sai định dạng.") from None
    if (choice.get("finish_reason") == "length" or not isinstance(translations, list)
            or any(not isinstance(part, str) for part in translations)):
        raise RuntimeError("Mô hình trả bản dịch chưa đầy đủ.")
    return translations


def translate_blocks(blocks):
    from huggingface_hub import hf_hub_download

    executable = shutil.which("llama-server")
    if not executable:
        raise RuntimeError("Cần cài llama-server để dịch kịch bản.")
    model_path = hf_hub_download(MODEL, MODEL_FILE, revision=REVISION)
    host = "127.0.0.1"
    with socket.socket() as listener:
        listener.bind((host, 0))
        port = listener.getsockname()[1]
    base_url = f"http://{host}:{port}"
    with tempfile.TemporaryFile() as log:
        server = subprocess.Popen(
            [executable, "--model", model_path, "--host", host, "--port", str(port),
             "--ctx-size", "12288", "--threads", "4", "--parallel", "1"],
            stdout=log, stderr=log,
        )
        try:
            wait_for_model(server, base_url)
            return request_translations(base_url, blocks)
        except RuntimeError:
            if server.poll() is not None:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - 1800))
                print(log.read().decode("utf-8", errors="replace"))
            raise
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


def prepare(title, script, target, source="auto"):
    if target != "de":
        return title, script
    source_language = language_of(script) if source == "auto" else source
    title_language = language_of(title)
    title_needs_translation = title_language == "vi" or (source_language != "de" and title_language != "de")
    paragraphs = [] if source_language == "de" else [paragraph_blocks(p) for p in script.split("\n\n")]
    blocks = ([title] if title_needs_translation else []) + [block for p in paragraphs for block in p]
    if not blocks:
        return title, script
    translations = translate_blocks(blocks)
    if len(translations) != len(blocks) or any(not part.strip() for part in translations):
        raise ValueError("Mô hình dịch trả thiếu tiêu đề hoặc lời thoại.")
    translated = iter(translations)
    if title_needs_translation:
        title = " ".join(next(translated).split())
    if paragraphs:
        script = "\n\n".join(" ".join(next(translated) for _ in p) for p in paragraphs)
        if len(script) > MAX_NARRATION_CHARS:
            raise ValueError("Lời đọc tiếng Đức vượt quá 10.000 ký tự.")
        if language_of(script) == "vi":
            raise ValueError("Lời đọc trả về vẫn là tiếng Việt.")
    return title, script


def main():
    parser = argparse.ArgumentParser(description="Chuẩn bị tiêu đề và lời đọc tiếng Đức.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--target", choices=("de", "vi", "en"), default="de")
    parser.add_argument("--source", choices=("auto", "vi", "de"), default="auto")
    args = parser.parse_args()
    try:
        title, script = prepare(args.title, read_script(args.script), args.target, args.source)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "title.txt").write_text(title + "\n", encoding="utf-8")
        (args.out / "script.txt").write_text(script + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Không chuẩn bị được bản lời đọc: {error}\n")
    print(f"Đã chuẩn bị bản lời đọc ({args.target}).")


if __name__ == "__main__":
    main()
