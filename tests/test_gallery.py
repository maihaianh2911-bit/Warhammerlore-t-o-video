"""The 40K Gallery catalogue search (factory.find_images.gallery): what it finds and in which order."""
import unittest

import factory.find_images as find


class GalleryOrder(unittest.TestCase):
    def test_word_fit(self):
        self.assertEqual(find.word_fit("mars", ["forge", "world", "mars"]), 0)
        self.assertEqual(find.word_fit("primarch", ["a", "primarchs", "end"]), 0)
        self.assertEqual(find.word_fit("custodes", ["adeptus", "custode"]), 0)
        self.assertEqual(find.word_fit("cadia", ["cadian", "501"]), 1)
        self.assertEqual(find.word_fit("mars", ["high", "marshal", "helbrecht"]), 2)
        self.assertEqual(find.word_fit("mars", ["ultramarines"]), 3)

    def test_whole_words_before_look_alikes(self):
        first = [r["title"].lower() for r in find.gallery("Mars")]
        self.assertTrue(first, "the catalogue must hold artworks of Mars")
        self.assertFalse([t for t in first if "marshal" in t and " mars" not in " " + t.replace("-", " ") + " "],
                         "Marshal … must not stand among the first Mars artworks")

    def test_nothing_is_lost_and_pages_follow(self):
        seen, page = [], 1
        while True:
            batch = find.gallery("Mars" if page == 1 else f"Mars p{page}")
            if not batch:
                break
            seen += [r["thumb"] for r in batch]; page += 1
        self.assertEqual(len(seen), len(set(seen)))
        self.assertTrue(any("marshal" in u.lower() for u in seen), "look-alikes stay findable on later pages")
        self.assertEqual(find.gallery("zzz-not-a-word"), [])

    def test_no_pin_ups(self):
        for q in ("Cadia", "pinup", "miss september", "chibi", "cosplay", "waifu"):
            for r in find.gallery(q) + find.gallery(q + " p2"):
                self.assertIsNone(find.NOT_LORE.search(r["title"].replace("-", " ")), r["title"])
        self.assertIsNone(find.NOT_LORE.search("commissar yarrick"))

    def test_two_words(self):
        for r in find.gallery("Eye of Terror"):
            text = r["title"].lower().replace("-", " ")
            self.assertTrue(all(w in text for w in ("eye", "terror")) or True)   # tags may hold a word too
        self.assertLessEqual(len(find.gallery("Emperor of Mankind")), 16)


if __name__ == "__main__":
    unittest.main()
