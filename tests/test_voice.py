import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch
from urllib.error import URLError

from factory.script import make_cues
from factory.vn11 import configuration, create_job, synthesize, verify_saved_clone
from factory.voice_check import align_words


class VN11Test(unittest.TestCase):
    def test_finds_configured_clone_across_pages(self):
        responses = [
            (200, {"voices": [{"name": "ww40k old", "voice_id": "clone_31"}], "has_more": True, "next_page": 2}),
            (200, {"voices": [{"name": "WW40K", "voice_id": "clone_611"}], "has_more": False}),
        ]
        with patch("factory.vn11.request_json", side_effect=responses) as request:
            verify_saved_clone("key", "clone_611")
        self.assertEqual(request.call_count, 2)
        self.assertIn("provider=clone&page=2", request.call_args.args[0])

    def test_refuses_another_voice_with_same_name(self):
        with patch("factory.vn11.saved_clones", return_value=[{"name": "ww40k", "voice_id": "clone_32"}]):
            with self.assertRaisesRegex(ValueError, "clone_611"):
                verify_saved_clone("key", "clone_611")

    def test_uses_the_supplied_voice_id_by_default(self):
        with patch.dict("os.environ", {"VN11_API_KEY": "key"}, clear=True):
            self.assertEqual(configuration(), ("key", "clone_611"))

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


class PaidVoiceTest(unittest.TestCase):
    """A reading VN11 was paid for survives everything that can break after it."""
    TEXT = "Eins zwei. Drei vier."

    def setUp(self):
        from factory.script import load_job
        folder = Path(tempfile.mkdtemp())
        (folder / "script.json").write_text(json.dumps({"title": "T", "paragraphs": [["Eins zwei.", "Drei vier."]]}),
                                            encoding="utf-8")
        self.job = load_job(folder / "script.json")
        self.out = folder / "voice"
        self.saved = []     # what was in the folder each time the caller was asked to store it

    def narrate(self, heard=None, **mocks):
        from factory import narrate as module
        words = heard or [(word, index * 0.5, index * 0.5 + 0.4) for index, word in enumerate(self.TEXT.split())]
        defaults = {
            "create_job": mock.Mock(return_value="job-1"),
            "poll_job": mock.Mock(return_value="https://example.com/a.mp3"),
            "save_audio": mock.Mock(side_effect=lambda url, path: path.write_bytes(b"mp3")),
        }
        defaults.update(mocks)
        with patch.dict("os.environ", {"VN11_API_KEY": "key"}), patch.object(module, "load_model"), \
                patch.object(module, "transcribe", return_value=words), \
                patch.object(module, "audio_duration", return_value=2.0), \
                patch.multiple(module, **defaults), contextlib.redirect_stdout(io.StringIO()):
            try:
                return module.narrate(self.job, self.out, self.out,
                                      checkpoint=lambda: self.saved.append(sorted(p.name for p in self.out.iterdir())))
            finally:
                self.calls = defaults

    def test_a_good_reading_leaves_only_the_voice(self):
        timing, reused = self.narrate()
        self.assertFalse(reused)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["check.md", "narration.mp3", "timing.json"])
        self.assertEqual(self.saved, [["pending.json"], ["pending.json", "take.mp3"]])   # stored before the check
        self.assertEqual(self.narrate()[1], True)                   # the same script again: nothing is paid
        self.calls["create_job"].assert_not_called()

    def test_a_reading_whisper_rejects_is_kept_and_not_paid_again(self):
        with self.assertRaisesRegex(ValueError, "take.mp3"):
            self.narrate(heard=[("völlig", 0.1, 0.4), ("anders", 0.5, 0.9)])
        self.assertEqual((self.out / "take.mp3").read_bytes(), b"mp3")
        self.assertFalse((self.out / "timing.json").exists())
        self.narrate()                                              # the next run checks the same audio
        self.calls["create_job"].assert_not_called()
        self.calls["poll_job"].assert_not_called()
        self.assertFalse((self.out / "take.mp3").exists())

    def test_a_download_that_breaks_continues_with_the_same_job(self):
        with self.assertRaises(RuntimeError):
            self.narrate(save_audio=mock.Mock(side_effect=RuntimeError("Không tải được tệp giọng từ VN11.")))
        self.assertEqual(json.loads((self.out / "pending.json").read_text(encoding="utf-8"))["job"], "job-1")
        self.narrate()
        self.calls["create_job"].assert_not_called()
        self.calls["poll_job"].assert_called_once_with("job-1", "key")

    def test_a_reading_vn11_lost_is_forgotten(self):
        from factory.vn11 import JobLost
        with self.assertRaisesRegex(RuntimeError, "lượt mới"):
            self.narrate(poll_job=mock.Mock(side_effect=JobLost("VN11 báo lượt tạo giọng thất bại.")))
        self.assertFalse((self.out / "pending.json").exists())
        self.narrate()
        self.calls["create_job"].assert_called_once()

    def test_a_changed_script_is_read_again(self):
        self.out.mkdir()
        (self.out / "pending.json").write_text(json.dumps({"text": "Alt.", "voice": "clone_611", "job": "old",
                                                           "audio": "take.mp3"}), encoding="utf-8")
        (self.out / "take.mp3").write_bytes(b"old")
        self.narrate()
        self.calls["create_job"].assert_called_once()
        self.assertEqual((self.out / "narration.mp3").read_bytes(), b"mp3")


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
