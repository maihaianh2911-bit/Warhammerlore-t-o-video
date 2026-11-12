import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from factory.script import make_cues
from factory.vn11 import create_job, synthesize
from factory.voice_check import align_words


class VN11Test(unittest.TestCase):
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
