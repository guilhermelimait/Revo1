import unittest

from revo1.media import TEXT_MAX, clean


class CleanTests(unittest.TestCase):
    def test_accents_keep_their_base_letter(self):
        self.assertEqual(clean("M\u00fasica \u2013 A\u00e7\u00e3o \u00e9 Stra\u00dfe"),
                         "Musica - Acao e Strasse")
        self.assertEqual(clean("\u201cBj\u00f6rk\u201d \u00c6on"), '"Bjork" AEon')

    def test_scripts_without_latin_letters_become_question_marks(self):
        self.assertEqual(clean("\u6771\u4eac"), "??")

    def test_long_text_is_shortened(self):
        text = clean("a" * 100)
        self.assertEqual(len(text), TEXT_MAX)
        self.assertTrue(text.endswith("~"))


if __name__ == "__main__":
    unittest.main()
