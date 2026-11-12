import unittest

from factory.art import choose_art, load_catalog
from factory.intake import read_issue
from factory.script import caption_spans, make_cues, make_shots


class PipelineTest(unittest.TestCase):
    def test_intake_uses_only_an_owner_issue(self):
        issue = {"user": {"login": "owner"}, "title": "[40K] Terra", "body": "<!-- mẫu -->\nLời đọc."}
        self.assertEqual(read_issue(issue, "Owner"), ("Terra", "Lời đọc."))
        with self.assertRaises(ValueError):
            read_issue(issue, "other")
        with self.assertRaises(ValueError):
            read_issue({**issue, "pull_request": {"url": "example"}}, "owner")

    def test_cues_use_original_characters_and_shots_cover_all_frames(self):
        text = "Guilliman trở lại.\n\nMột khe nứt chia cắt thiên hà.\n\nTerra vẫn đứng vững."
        starts = [index * 0.16 for index in range(len(text))]
        ends = [time + 0.16 for time in starts]
        cues = make_cues(text, starts, ends, ends[-1])
        self.assertEqual([cue.text for cue in cues], [text[a:b] for a, b in caption_spans(text)])
        self.assertTrue(all(a.end <= b.start for a, b in zip(cues, cues[1:])))
        frames = round(ends[-1] * 30)
        shots = make_shots(cues, frames, 30)
        self.assertEqual((shots[0].start_frame, shots[-1].end_frame), (0, frames))
        self.assertTrue(all(a.end_frame == b.start_frame for a, b in zip(shots, shots[1:])))

    def test_art_respects_era_and_keeps_gallery_links(self):
        catalog = load_catalog()
        catalog["assets"] = [
            {"keywords": ["guilliman"], "source": "https://example.com/30k", "require_any": ["heresy"]},
            {"keywords": ["guilliman"], "source": "https://example.com/40k", "require_any": ["great rift"]},
        ]
        theme, references, pictures = choose_art(catalog, "Guilliman after the Great Rift", None, 0)
        self.assertEqual(theme, "orbit")
        self.assertEqual(references[0]["url"], "https://40k.gallery/tag/roboute-guilliman/")
        self.assertEqual([item["source"] for item in pictures], ["https://example.com/40k"])
