import json
import tempfile
import unittest
from pathlib import Path

from factory.attachments import attachment_urls, owner_texts
from factory.run import todo
from factory.render import camera_view, centred, default_move, eased
from factory.script import MOVES, caption_chunks, chunk_events, line_times, load_job, load_picks, shot_frames


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

    def test_accepts_pictures_and_backgrounds(self):
        picks = {"images": {**self.images, "b": {"src": "art/b.jpg", "credit": "B"}},
                 "shots": [{"img": "b", "focus": [0.6, 0.3]}, {"at": 2.5, "img": "a", "zoom": 1.3}, {"at": 3, "theme": "rift"}]}
        self.assertEqual(len(load_picks(write(picks), 3)[1]), 3)

    def test_refuses_what_the_renderer_cannot_place(self):
        cases = {
            "credit": {"images": {"a": {"src": "issue/1.jpg"}}, "shots": [{"img": "a"}]},
            "chưa khai báo": {"images": self.images, "shots": [{"img": "missing"}]},
            "tăng dần": {"images": self.images, "shots": [{"img": "a"}, {"at": 3, "img": "a"}, {"at": 2, "img": "a"}]},
            "từ 1 đến 3": {"images": self.images, "shots": [{"img": "a"}, {"at": 4, "img": "a"}]},
            "theme": {"images": self.images, "shots": [{"at": 1}]},
            "focus": {"images": self.images, "shots": [{"img": "a", "focus": [2, 0]}]},
            "trọng tâm": {"images": self.images, "shots": [{"img": "a", "to": [1.2, 0.5, 0.5]}]},
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


class MotionTest(unittest.TestCase):
    def test_every_move_ends_centred_on_the_subject(self):
        from PIL import Image
        for size in ((200, 400), (600, 400)):               # a tall picture and a wide one
            picture = Image.new("RGB", size)
            picture.putpixel((round(0.6 * size[0]), 160), (255, 255, 255))          # the subject: focus (0.6, 0.4)
            for kind in MOVES:
                with self.subTest(kind=kind, size=size):
                    start, end = default_move((0.6, 0.4), 6, kind, (*size, 0.5))
                    self.assertEqual(end[0] < start[0], kind == "pull")
                    moved = abs(end[0] - start[0]) + abs(end[1] - start[1]) + abs(end[2] - start[2])
                    self.assertGreater(moved, 0.15)                 # a shot never looks still
                    self.assertLessEqual(max(start[0], end[0]), 1.6)    # the scene is never lost
                    view = camera_view(picture, end, (200, 400)).convert("L")
                    brightest = max(range(200 * 400), key=view.tobytes().__getitem__)
                    self.assertLessEqual(abs(brightest % 200 - 100), 8)
                    self.assertLessEqual(abs(brightest // 200 - 200), 8)

    def test_a_wide_picture_gives_room_to_sweep_sideways(self):
        start, end = default_move((0.2, 0.5), 6, "from-right", (1600, 900, 0.5625))
        self.assertGreater(start[1] - end[1], 0.4)

    def test_the_view_stays_inside_the_picture(self):
        self.assertEqual(centred(2.0, (0.02, 0.98), (200, 400, 0.5)), (2.0, 0.25, 0.75))
        self.assertEqual(centred(1.0, (0.2, 0.2), (200, 400, 0.5)), (1.0, 0.5, 0.5))

    def test_motion_settles_without_stopping(self):
        self.assertEqual((eased(0), eased(1)), (0, 1))
        self.assertGreater(eased(0.1) - eased(0), eased(1) - eased(0.9))
        self.assertGreater(eased(1) - eased(0.9), 0.03)


class CaptionTest(unittest.TestCase):
    def test_captions_follow_the_words(self):
        text = "Im 41. Jahrtausend gibt es nur Krieg. Niemand ruft."
        starts = [index * 0.1 for index in range(len(text))]
        ends = [value + 0.1 for value in starts]
        chunks = caption_chunks(text, starts, ends, len(text) * 0.1)
        self.assertEqual([" ".join(word for word, _, _ in chunk) for chunk in chunks],
                         ["Im 41.", "Jahrtausend gibt", "es nur Krieg.", "Niemand ruft."])
        events = chunk_events(chunks, len(text) * 0.1)
        self.assertEqual(len(events), 9)
        self.assertTrue(all(first[1] <= second[0] + 1e-9 for first, second in zip(events, events[1:])))
        self.assertIn("Krieg.", events[4][2])


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
