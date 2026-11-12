import unittest
from unittest.mock import patch

from factory.translate import MAX_BLOCK_CHARS, paragraph_blocks, prepare, protect_names, remove_added_title, restore_names


class TranslationTest(unittest.TestCase):
    def test_translates_title_and_narration_in_order(self):
        source = "Ai đứng trước cổng?\n\nGuilliman nhìn về Terra."
        with (
            patch("factory.translate.language_of", side_effect=["vi", "vi", "de"]),
            patch("factory.translate.translate_blocks", return_value=[
                "Vor den Toren von Terra", "Wer steht vor dem Tor?", "Guilliman blickt nach Terra.",
            ]) as model,
        ):
            title, script = prepare("Trước cổng thành Terra", source, "de")
        model.assert_called_once_with(
            ["Trước cổng thành Terra", "Ai đứng trước cổng?", "Guilliman nhìn về Terra."], separate_title=True,
        )
        self.assertEqual(title, "Vor den Toren von Terra")
        self.assertEqual(script, "Wer steht vor dem Tor?\n\nGuilliman blickt nach Terra.")

    def test_preserves_german_narration_and_localizes_vietnamese_title(self):
        german = "Guilliman kehrte nach Terra zurück."
        with (
            patch("factory.translate.language_of", side_effect=["de", "vi"]),
            patch("factory.translate.translate_blocks", return_value=["Die Rückkehr nach Terra"]) as model,
        ):
            self.assertEqual(prepare("Trở về Terra", german, "de"), ("Die Rückkehr nach Terra", german))
        model.assert_called_once_with(["Trở về Terra"], separate_title=True)

    def test_leaves_existing_german_and_other_configured_languages_alone(self):
        with (
            patch("factory.translate.language_of", return_value="de"),
            patch("factory.translate.translate_blocks") as model,
        ):
            self.assertEqual(prepare("Die Rückkehr", "Guilliman kehrte zurück.", "de"),
                             ("Die Rückkehr", "Guilliman kehrte zurück."))
            self.assertEqual(prepare("The return", "Guilliman returned.", "en"),
                             ("The return", "Guilliman returned."))
        model.assert_not_called()

    def test_long_paragraphs_split_without_dropping_text(self):
        paragraph = " ".join(["Guilliman nhìn về Terra."] * 80)
        parts = paragraph_blocks(paragraph)
        self.assertTrue(all(len(part) <= MAX_BLOCK_CHARS for part in parts))
        self.assertEqual(" ".join(parts), paragraph)

    def test_proper_names_are_restored_only_when_all_markers_are_present(self):
        text, names = protect_names("Roboute Guilliman trở về Terra.")
        self.assertEqual(text, "[NAME0] trở về [NAME1].")
        self.assertEqual(restore_names("[NAME0] kehrt nach [NAME1] zurück.", names),
                         "Roboute Guilliman kehrt nach Terra zurück.")
        with self.assertRaisesRegex(ValueError, "Terra"):
            restore_names("[NAME0] kehrt zurück.", names)

    def test_removes_only_an_inserted_title_after_the_last_sentence(self):
        self.assertEqual(
            remove_added_title("Trở về Terra", "Họ đã biến mất.", "Rückkehr nach Terra",
                               "Sie verschwanden. Rückkehr nach Terra"),
            "Sie verschwanden.",
        )
        self.assertEqual(
            remove_added_title("Trở về Terra", "Họ nói. Trở về Terra.", "Rückkehr nach Terra",
                               "Sie sagten es. Rückkehr nach Terra."),
            "Sie sagten es. Rückkehr nach Terra.",
        )

    def test_stops_before_narration_if_translation_omits_a_block(self):
        with (
            patch("factory.translate.language_of", return_value="vi"),
            patch("factory.translate.translate_blocks", return_value=["Ein Titel"]),
        ):
            with self.assertRaises(ValueError):
                prepare("Tiêu đề", "Lời thoại đã duyệt.", "de")
