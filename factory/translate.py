import argparse
import re
import textwrap
from pathlib import Path

from .script import read_script


MODEL = "cstr/madlad400-3b-ct2-int8"
REVISION = "fd0b55729c074372eb84b52b9309a00dc65c40c4"
MAX_BLOCK_CHARS = 760
MAX_NARRATION_CHARS = 10_000


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


def translate_blocks(blocks):
    from ctranslate2 import Translator
    from huggingface_hub import snapshot_download
    from sentencepiece import SentencePieceProcessor

    directory = Path(snapshot_download(
        MODEL, revision=REVISION,
        allow_patterns=["config.json", "model.bin", "shared_vocabulary.json", "spiece.model"],
    ))
    tokenizer = SentencePieceProcessor(model_file=str(directory / "spiece.model"))
    inputs = [tokenizer.encode(f"<2de> {block}", out_type=str) for block in blocks]
    translator = Translator(str(directory), device="cpu", compute_type="int8", intra_threads=4)
    results = translator.translate_batch(
        inputs, batch_type="tokens", max_batch_size=768,
        beam_size=3, max_decoding_length=600, no_repeat_ngram_size=4,
    )
    return [tokenizer.decode(result.hypotheses[0]).strip() for result in results]


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
