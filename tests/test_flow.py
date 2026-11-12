import json
import tempfile
import unittest
from pathlib import Path

from factory.attachments import attachment_urls, owner_texts
from factory.run import todo
from factory.script import line_times, load_job, load_picks, shot_frames


def write(data):
    folder = Path(tempfile.mkdtemp())
    path = folder / "file.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class JobTest(unittest.TestCase):
    def test_lines_keep_their_place_in_the_narration(self):
        job = load_job(write({"title": " Wer  kommt? ", "paragraphs": [["Im 41. Jahrtausend.", "Nur Krieg."], ["Ende."]]}))
        self.assertEqual(job.title, "Wer kommt?")
        self.assertEqual(job.text, "Im 41. Jahrtausend. Nur Krieg.\n\nEnde.")
        self.assertEqual([job.text[a:b] for a, b in job.spans], ["Im 41. Jahrtausend.", "Nur Krieg.", "Ende."])

    def test_refuses_empty_lines_and_overlong_scripts(self):
        with self.assertRaisesRegex(ValueError, "Câu số 2"):
            load_job(write({"title": "T", "paragraphs": [["Eins.", " "]]}))
        with self.assertRaisesRegex(ValueError, "vượt giới hạn"):
            load_job(write({"title": "T", "paragraphs": [["a" * 10_001]]}))


class PicksTest(unittest.TestCase):
    images = {"a": {"src": "issue/1.jpg", "credit": "Künstler — Titel"}}

    def test_accepts_pictures_collages_and_backgrounds(self):
        picks = {"images": {**self.images, "b": {"src": "art/b.jpg", "credit": "B"}},
                 "shots": [{"collage": ["a", "b"], "pan": True}, {"at": 2.5, "img": "a"}, {"at": 3, "theme": "rift"}]}
        self.assertEqual(len(load_picks(write(picks), 3)[1]), 3)

    def test_refuses_what_the_renderer_cannot_place(self):
        cases = {
            "credit": {"images": {"a": {"src": "issue/1.jpg"}}, "shots": [{"img": "a"}]},
            "chưa khai báo": {"images": self.images, "shots": [{"img": "missing"}]},
            "tăng dần": {"images": self.images, "shots": [{"img": "a"}, {"at": 3, "img": "a"}, {"at": 2, "img": "a"}]},
            "từ 1 đến 3": {"images": self.images, "shots": [{"img": "a"}, {"at": 4, "img": "a"}]},
            "theme": {"images": self.images, "shots": [{"at": 1}]},
        }
        for message, picks in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                load_picks(write(picks), 3)

    def test_shots_cut_where_their_line_starts(self):
        times = [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
        shots = [{"img": "a"}, {"at": 2, "img": "a"}, {"at": 3.5, "img": "a"}]
        self.assertEqual(shot_frames(shots, times, 180, 30), [(0, 60), (60, 150), (150, 180)])
        with self.assertRaisesRegex(ValueError, "nửa giây"):
            shot_frames([{"img": "a"}, {"at": 1.1, "img": "a"}], times, 180, 30)

    def test_line_times_follow_the_voice(self):
        self.assertEqual(line_times([(0, 2), (3, 5)], [0, 1, 2, 3, 4], [1, 2, 3, 4, 5]), [(0, 2), (3, 5)])


class RunTest(unittest.TestCase):
    def test_changed_files_choose_the_steps(self):
        files = ["lore/7/picks.json", "lore/7/script.json", "lore/8/search-2.json", "lore/8/own/a.jpg",
                 "lore/9/notes.txt", "factory/run.py"]
        self.assertEqual(todo(files), ["7 prepare render", "8 search render"])

    def test_only_the_owners_attachments_are_collected(self):
        url = "https://github.com/user-attachments/assets/0f8fad5b-d9cb-469f-a165-70867728950e"
        issue = {"user": {"login": "Owner"}, "body": f"![a]({url}) và https://evil.example/x.png"}
        comments = [
            {"user": {"login": "guest"}, "body": url.replace("0f8f", "1111")},
            {"user": {"login": "owner"}, "body": f"lại {url}"},
        ]
        self.assertEqual(attachment_urls(owner_texts(issue, comments, "owner")), [url])


if __name__ == "__main__":
    unittest.main()
