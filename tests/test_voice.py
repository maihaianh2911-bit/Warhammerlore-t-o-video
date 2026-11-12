import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from factory.script import make_cues
from factory.vn11 import configuration, create_job, resolve_voice, synthesize
from factory.voice_check import align_words


class VN11Test(unittest.TestCase):
    def test_finds_saved_voice_by_exact_name_across_pages(self):
        responses = [
            (200, {"voices": [{"name": "ww40k old", "voice_id": "clone_31"}], "has_more": True, "next_page": 2}),
            (200, {"voices": [{"name": "WW40K", "voice_id": "clone_32"}], "has_more": False}),
        ]
        with patch("factory.vn11.request_json", side_effect=responses) as request:
            self.assertEqual(resolve_voice("key", "ww40k"), "clone_32")
        self.assertEqual(request.call_count, 2)
        self.assertIn("provider=clone&page=2", request.call_args.args[0])

    def test_only_uses_a_unique_prefix(self):
        with patch("factory.vn11.list_voices", side_effect=[
            [{"name": "WW40K DE", "voice_id": "clone_32"}], [],
        ]):
            self.assertEqual(resolve_voice("key", "ww40k"), "clone_32")
        with patch("factory.vn11.list_voices", side_effect=[
            [{"name": "ww40k A", "voice_id": "clone_32"}, {"name": "ww40k B", "voice_id": "clone_33"}], [],
        ]):
            with self.assertRaisesRegex(ValueError, "nhiều giọng"):
                resolve_voice("key", "ww40k")

    def test_configured_name_takes_priority_over_an_old_id(self):
        with (
            patch.dict("os.environ", {"VN11_API_KEY": "key", "VN11_VOICE_NAME": "ww40k", "VN11_VOICE_ID": "clone_190"}),
            patch("factory.vn11.resolve_voice", return_value="clone_32") as resolve,
        ):
            self.assertEqual(configuration(), ("key", "clone_32"))
        resolve.assert_called_once_with("key", "ww40k")

    def test_german_uses_provider_language_setting(self):
        with patch("factory.vn11.request_json", return_value=(200, {"job_id": "job"})) as request:
            create_job("Das ist ein Test.", "de", "key", "voice")
        self.assertEqual(json.loads(request.call_args.args[2])["voice_settings"]["language"], "German")

    def test_non_clone_uses_language_and_sends_all_text_once(self):
        text = "Đây là câu đầu.\n\nĐây là câu tiếp."
        with patch("factory.vn11.request_json", return_value=(200, {"job_id": "job"})) as request:
            self.assertEqual(create_job(text, "vi", "key", "voice"), "job")
        request.assert_called_once()
        path, _, body, content_type = request.call_args.args
        self.assertEqual((path, content_type), ("tts.php", "application/json"))
        data = json.loads(body)
        self.assertEqual(data["text"], text)
        self.assertEqual(data["voice_settings"]["language"], "Vietnamese")

    def test_clone_is_created_once_and_only_the_poll_retries(self):
        responses = [
            (200, {"job_id": "job 2"}), (503, {}), URLError("temporary"),
            (200, {"status": "completed", "download_url": "https://example.com/audio"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            with (
                patch("factory.vn11.request_json", side_effect=responses) as request,
                patch("factory.vn11.time.sleep"),
                patch("factory.vn11.save_audio") as save,
            ):
                self.assertEqual(synthesize("Guilliman.", "en", scratch, "key", "clone_190"), scratch / "voice.mp3")
            save.assert_called_once_with("https://example.com/audio", scratch / "voice.mp3")
        paths = [call.args[0] for call in request.call_args_list]
        self.assertEqual(paths, ["clone.php", "status.php?job_id=job+2", "status.php?job_id=job+2",
                                 "status.php?job_id=job+2"])


class VoiceAlignmentTest(unittest.TestCase):
    def test_preserves_script_and_flags_names_whisper_heard_differently(self):
        text = "Guilliman đã trở về. Terra vẫn đứng vững."
        words = ["Gilliman", "đã", "trở", "về.", "Terra", "vẫn", "đứng", "vững."]
        heard = [(word, 0.2 + i * 0.4, 0.5 + i * 0.4) for i, word in enumerate(words)]
        starts, ends, report = align_words(text, heard, 3.7)
        self.assertEqual(report["review"][0]["script"], "Guilliman")
        self.assertEqual(report["review"][0]["heard"], "Gilliman")
        cues = make_cues(text, starts, ends, 3.7)
        self.assertTrue(cues[0].text.startswith("Guilliman"))
        self.assertEqual(cues[0].start, 0.2)
        self.assertTrue(all(a.end <= b.start for a, b in zip(cues, cues[1:])))

    def test_rejects_an_unrelated_read(self):
        with self.assertRaises(ValueError):
            align_words("Terra vẫn đứng vững.", [("unrelated", 0.1, 0.4)], 0.5)
