import json
import tempfile
import unittest
from pathlib import Path

from factory.attachments import attachment_urls, owner_texts
from factory.run import catch_up, matrix, todo
from factory.render import along, camera_view, centred, default_move, eased
from factory.script import (MAX_NARRATION_CHARS, MOVES, caption_chunks, caption_spans, chunk_events, line_times, load_job,
                            load_picks, make_cues, sentence_end, shot_frames)


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
            load_job(write({"title": "T", "paragraphs": [["a" * (MAX_NARRATION_CHARS + 1)]]}))
        # the voice may last 600 s and ww40k reads ~15.6 characters a second: a longer script must fail before the
        # paid reading, not after it
        self.assertLessEqual(MAX_NARRATION_CHARS, 600 * 15)


class PicksTest(unittest.TestCase):
    images = {"a": {"src": "issue/1.jpg", "credit": "Künstler — Titel"}}

    def test_accepts_pictures_and_backgrounds(self):
        picks = {"images": {**self.images, "b": {"src": "art/b.jpg", "credit": "B"}},
                 "shots": [{"img": "b", "focus": [0.6, 0.3], "move": "pull", "pace": "even"},
                           {"at": 2.5, "img": "a", "focus": [0.5, 0.2], "from": [1.2, 0.5, 0.9], "via": [[0.4, 1.1, 0.5, 0.5]], "zoom": 1.3},
                           {"at": 3, "theme": "rift"}]}
        self.assertEqual(len(load_picks(write(picks), 3)[1]), 3)

    def test_refuses_what_the_renderer_cannot_place(self):
        cases = {
            "credit": {"images": {"a": {"src": "issue/1.jpg"}}, "shots": [{"img": "a"}]},
            "chưa khai báo": {"images": self.images, "shots": [{"img": "missing"}]},
            "cách đi máy": {"images": self.images, "shots": [{"img": "a", "focus": [0.5, 0.3]}]},
            "đổi hướng": {"images": self.images, "shots": [{"img": "a", "focus": [0.5, 0.3], "from": [1.0, 0.2, 0.5], "via": [[0.5, 1.0, 0.8, 0.5]]}]},
            "via": {"images": self.images, "shots": [{"img": "a", "focus": [0.5, 0.3], "move": "push", "via": [[0.6, 1.2, 0.5, 0.5], [0.3, 1.2, 0.5, 0.5]]}]},
            "tăng dần": {"images": self.images, "shots": [{"theme": "rift"}, {"at": 3, "theme": "rift"}, {"at": 2, "theme": "rift"}]},
            "từ 1 đến 3": {"images": self.images, "shots": [{"theme": "rift"}, {"at": 4, "theme": "rift"}]},
            "theme": {"images": self.images, "shots": [{"at": 1}]},
            "focus là": {"images": self.images, "shots": [{"img": "a", "focus": [2, 0], "move": "push"}]},
            "không đặt to": {"images": self.images, "shots": [{"img": "a", "focus": [0.5, 0.5], "move": "push", "to": [1.2, 0.5, 0.5]}]},
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

    def test_the_camera_passes_through_its_keyframes(self):
        keys = [(0.0, (1.0, 0.5, 0.5)), (0.5, (1.2, 0.2, 0.6)), (1.0, (1.4, 0.6, 0.3))]
        self.assertEqual(along(keys, 0.5), (1.2, 0.2, 0.6))
        self.assertEqual(along(keys, 1.0), (1.4, 0.6, 0.3))
        self.assertAlmostEqual(along(keys, 0.25)[0], 1.1)
        for pace in ("settle", "even", "surge"):
            self.assertEqual((eased(0, pace), eased(1, pace)), (0, 1))
        self.assertLess(eased(0.5, "surge"), 0.5)

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


    def test_ordinals_and_abbreviations_do_not_end_a_sentence(self):
        for word in ("41.", "3.", "z.", "B.", "d.h.", "Dr.", "St.", "Nr.", "bzw.", "ca.", "„41."):
            with self.subTest(word):
                self.assertFalse(sentence_end(word))
        for word in ("Krieg.", "usw.", "etc.", "ruft!", "wer?", "Ende.«", "Tor…?", "Krieg...", "Sanguinius.\""):
            with self.subTest(word):
                self.assertTrue(sentence_end(word))
        self.assertFalse(sentence_end("Krieg,"))

    def test_srt_keeps_ordinals_with_their_noun(self):
        text = "Im 41. Jahrtausend gibt es nur Krieg. Dr. Vox kam z. B. am 3. Mai. Das war usw. Dann Ende."
        cues = [text[a:b] for a, b in caption_spans(text)]
        self.assertEqual(cues, ["Im 41. Jahrtausend gibt es nur Krieg.", "Dr. Vox kam z. B. am 3. Mai.",
                                "Das war usw.", "Dann Ende."])

    def test_a_script_line_always_closes_a_caption(self):
        text = "Es geschah im Jahr 999. Dann kam der Sturm."
        self.assertEqual([text[a:b] for a, b in caption_spans(text)], [text])
        self.assertEqual([text[a:b] for a, b in caption_spans(text, [23])],
                         ["Es geschah im Jahr 999.", "Dann kam der Sturm."])
        starts = [index * 0.1 for index in range(len(text))]
        ends = [value + 0.1 for value in starts]
        cues = make_cues(text, starts, ends, len(text) * 0.1, [23, len(text)])
        self.assertEqual([cue.text for cue in cues], ["Es geschah im Jahr 999.", "Dann kam der Sturm."])
        chunks = caption_chunks(text, starts, ends, len(text) * 0.1, [23, len(text)])
        self.assertEqual(chunks[1][-1][0], "999.")

    def test_a_long_sentence_is_not_cut_after_an_ordinal(self):
        text = "Im 41. Jahrtausend kämpfen die Weltraumhaie der Carcharodons in den Tiefen des Alls gegen alle Feinde."
        for first, last in caption_spans(text):
            self.assertFalse(text[first:last].endswith("41."), text[first:last])

    def test_burned_in_captions_keep_a_short_ordinal_with_its_noun(self):
        text = "Am 3. Mai fiel Cadia."
        starts = [index * 0.1 for index in range(len(text))]
        ends = [value + 0.1 for value in starts]
        chunks = caption_chunks(text, starts, ends, len(text) * 0.1)
        self.assertEqual([" ".join(word for word, _, _ in chunk) for chunk in chunks], ["Am 3. Mai", "fiel Cadia."])


class RunTest(unittest.TestCase):
    def test_changed_files_choose_the_steps(self):
        files = ["lore/7/picks.json", "lore/7/script.json", "lore/8/search-2.json", "lore/8/own/a.jpg",
                 "lore/9/notes.txt", "factory/run.py"]
        self.assertEqual(todo(files), ["7 prepare render", "8 search render"])

    def test_one_job_per_issue(self):
        self.assertEqual(matrix(["7 prepare render", "", "8 search", "x render", "9 rm -rf"]),
                         [{"n": "7", "steps": "prepare render"}, {"n": "8", "steps": "search"}])
        self.assertEqual(matrix([]), [])

    def test_a_run_does_what_a_replaced_run_left_undone(self):
        job, work = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        script = {"title": "T", "paragraphs": [["Eins.", "Zwei."]]}
        (job / "script.json").write_text(json.dumps(script), encoding="utf-8")
        self.assertEqual(catch_up(job, work, ["render"]), ["prepare", "render"])          # nothing was read yet
        (work / "voice").mkdir()
        (work / "voice" / "timing.json").write_text(json.dumps({"text": "Eins. Zwei."}), encoding="utf-8")
        self.assertEqual(catch_up(job, work, ["render"]), ["render"])                     # the voice is this script
        (work / "voice" / "timing.json").write_text(json.dumps({"text": "Eins. Drei."}), encoding="utf-8")
        self.assertEqual(catch_up(job, work, ["render"]), ["prepare", "render"])          # the script was fixed since
        self.assertEqual(catch_up(job, work, ["prepare"]), ["prepare"])
        (work / "voice" / "timing.json").write_text(json.dumps({"text": "Eins. Zwei."}), encoding="utf-8")
        (job / "search-2.json").write_text('{"queries": ["gallery:Badab"]}', encoding="utf-8")
        self.assertEqual(catch_up(job, work, ["render"]), ["search", "render"])           # round 2 never ran
        (work / "img" / "2").mkdir(parents=True)
        (work / "img" / "2" / "index.json").write_text("[]", encoding="utf-8")
        self.assertEqual(catch_up(job, work, ["render"]), ["render"])
        (job / "script.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(catch_up(job, work, ["render"]), ["render"])                     # reported by the step itself

    def test_claude_is_woken_once_the_pictures_are_there(self):
        from unittest import mock
        import factory.run as run_module

        class FakeRun:
            def __init__(self, number):
                self.calls, self.job, self.work = [], Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
                runs.append(self)

            def fetch_renders(self):
                pass

            def prepare(self):
                self.calls.append("prepare")
                return {"lines": [1], "duration": 3, "review": []}, 0, True

            def search(self):
                self.calls.append("search")

            def labels(self, add=(), remove=()):
                self.calls.append(("labels", tuple(add)))

            def comment(self, body):
                self.calls.append("comment")

            def wake(self, why, facts="", promise=""):
                self.calls.append(("wake", why, facts, promise))

        for steps, wanted in ((["search"], "đã tìm thêm hình"), (["prepare", "search"], "giọng và ảnh"),
                              (["prepare"], "giọng và ảnh")):
            runs = []
            with self.subTest(steps), mock.patch.object(run_module, "Run", FakeRun), \
                    mock.patch("sys.argv", ["run", "7", *steps]):
                run_module.main()
                wakes = [call for call in runs[0].calls if call[0] == "wake"]
                self.assertEqual(len(wakes), 1, runs[0].calls)
                self.assertIn(wanted, wakes[0][1])
                self.assertEqual(runs[0].calls[-1][0], "wake")      # only after every picture round is published
                # the machine's own comment goes through the wake, which alone may add what Claude does next
                self.assertNotIn("comment", runs[0].calls)
                self.assertNotIn("Claude sẽ", wakes[0][2])

    def test_a_failed_picture_search_is_recorded_and_only_it_is_tried_again(self):
        import io
        import sys
        from unittest import mock
        from PIL import Image
        import factory.find_images as find
        from factory.run import failed_queries, search_note

        def picture(seed):
            import random
            rng = random.Random(seed)       # coarse random blocks: three clearly different pictures
            small = Image.new("L", (9, 9))
            small.putdata([rng.randrange(256) for _ in range(81)])
            image = small.resize((600, 600), Image.BICUBIC).convert("RGB")
            data = io.BytesIO()
            image.save(data, "JPEG")
            return data.getvalue()

        pictures = {f"https://example.invalid/{seed}.jpg": picture(seed) for seed in (2, 5, 11)}
        down = {"badab"}

        def search(query, n=12):
            if query in down:
                raise TimeoutError("timed out")
            seeds = {"sharks": (2, 5), "badab": (11,)}[query]
            return [{"title": str(seed), "page": "p", "thumb": f"https://example.invalid/{seed}.jpg", "width": None,
                     "height": None, "source": "wiki", "license": "© GW"} for seed in seeds]

        out = Path(tempfile.mkdtemp()) / "1"
        queries = ["sharks", "badab"]

        def run():
            with mock.patch.object(find, "search", search), mock.patch.object(find, "get", pictures.__getitem__), \
                    mock.patch.object(find.time, "sleep"), mock.patch.object(sys, "argv", ["find", str(out), *queries]), \
                    mock.patch.dict("os.environ", {"FIND_SEEN": ""}):
                find.main()
            return json.loads((out / "index.json").read_text(encoding="utf-8"))

        index = run()
        self.assertEqual([len(entry["results"]) for entry in index], [2, 0])
        self.assertIn("TimeoutError", index[1]["error"])
        self.assertNotIn("error", index[0])
        self.assertEqual(failed_queries(out / "index.json", queries), ["badab"])
        self.assertEqual(failed_queries(out / "index.json", ["other"]), [])
        self.assertIn("badab", search_note(["badab"]))
        self.assertNotIn("Hình đã tìm xong", search_note(["badab"]))
        first = (out / "1-1.jpg").stat().st_mtime_ns

        down.clear()
        with mock.patch.dict(pictures, {"https://example.invalid/2.jpg": b"not a picture any more"}):
            index = run()       # "sharks" is not searched again: its pictures and numbers stay
        self.assertEqual([len(entry["results"]) for entry in index], [2, 1])
        self.assertEqual((out / "1-1.jpg").stat().st_mtime_ns, first)
        self.assertTrue((out / "2-1.jpg").is_file())
        self.assertEqual(failed_queries(out / "index.json", queries), [])

    def test_a_dropped_connection_is_tried_again(self):
        from unittest import mock
        from urllib.error import HTTPError, URLError
        import factory.find_images as find

        class Reply:
            def __enter__(self): return self
            def __exit__(self, *rest): return False
            def read(self): return b"ok"

        for errors in ([URLError("reset"), TimeoutError("slow")], [HTTPError("u", 502, "bad", {}, None)]):
            with mock.patch.object(find.urllib.request, "urlopen", side_effect=[*errors, Reply()]) as opened, \
                    mock.patch.object(find.time, "sleep"):
                self.assertEqual(find.get("https://example.invalid/x"), b"ok")
            self.assertEqual(opened.call_count, len(errors) + 1)
        with mock.patch.object(find.urllib.request, "urlopen", side_effect=HTTPError("u", 404, "no", {}, None)) as opened, \
                mock.patch.object(find.time, "sleep"):
            with self.assertRaises(HTTPError):
                find.get("https://example.invalid/x")
        self.assertEqual(opened.call_count, 1)

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
