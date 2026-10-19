import unittest

from lemma import lesson as L
from lemma import server


def matches(quote: str, source: str) -> bool:
    return L.quote_in_source(quote, L.normalize_for_match(source))


class LooseQuotesFail(unittest.TestCase):
    def test_quote_starting_mid_word_does_not_match(self):
        source = "The drug was an ineffective treatment for most patients in the trial, the authors concluded."
        self.assertFalse(matches("effective treatment for most patients in the trial", source))

    def test_quote_ending_mid_word_does_not_match(self):
        self.assertFalse(matches("the results were not signific", "the results were not significant at all"))

    def test_dropped_decimal_point_does_not_match(self):
        self.assertFalse(matches("Risk fell by 15 percent overall", "In the cohort, Risk fell by 1.5 percent overall."))

    def test_dropped_minus_sign_does_not_match(self):
        self.assertFalse(matches("Correlation was 0.3", "Correlation was -0.3 in the second sample."))
        self.assertFalse(matches("Correlation was 0.3", "Correlation was −0.3 in the second sample."))

    def test_added_minus_sign_does_not_match(self):
        self.assertFalse(matches("Correlation was -0.3 in the sample", "Correlation was 0.3 in the sample"))

    def test_empty_or_punctuation_only_quote_does_not_match(self):
        self.assertFalse(matches("", "anything at all"))
        self.assertFalse(matches("— ... —", "anything — ... — at all"))


class FaithfulQuotesMatch(unittest.TestCase):
    SOURCE = (
        "Abstract. The ﬁrst result is that trans-\nmission falls “quickly” once the\n  rate—measured weekly—drops "
        "below 1.5 per cent; it isn’t the only factor. Correlation was −0.3 overall. Over 1,200 people joined. "
        "Soft hy­phens vanish. This sentence closes the paper"
    )

    def test_case_differs(self):
        self.assertTrue(matches("the FIRST RESULT is that", self.SOURCE))

    def test_word_hyphenated_across_a_line_break(self):
        self.assertTrue(matches("that transmission falls", self.SOURCE))

    def test_ligature_in_source(self):
        self.assertTrue(matches("The first result is", self.SOURCE))

    def test_straight_quotes_and_apostrophes(self):
        self.assertTrue(matches("falls \"quickly\" once", self.SOURCE))
        self.assertTrue(matches("it isn't the only factor", self.SOURCE))

    def test_hyphen_or_spaced_dash_for_em_dash(self):
        self.assertTrue(matches("rate - measured weekly - drops below", self.SOURCE))
        self.assertTrue(matches("rate -- measured weekly -- drops below", self.SOURCE))
        self.assertTrue(matches("rate – measured weekly – drops below", self.SOURCE))

    def test_whitespace_and_line_breaks(self):
        self.assertTrue(matches("once   the rate", self.SOURCE))
        self.assertTrue(matches("once the\nrate", self.SOURCE))

    def test_numbers_with_decimals_signs_and_thousands(self):
        self.assertTrue(matches("drops below 1.5 per cent", self.SOURCE))
        self.assertTrue(matches("Correlation was -0.3 overall.", self.SOURCE))
        self.assertTrue(matches("Over 1,200 people joined", self.SOURCE))

    def test_soft_hyphen(self):
        self.assertTrue(matches("Soft hyphens vanish", self.SOURCE))

    def test_quote_at_start_and_end_of_source(self):
        self.assertTrue(matches("Abstract. The first result", self.SOURCE))
        self.assertTrue(matches("This sentence closes the paper.", self.SOURCE))

    def test_compound_hyphenated_across_a_line_break(self):
        self.assertTrue(matches("a well-known result", "this is a well-\nknown result"))

    def test_scanned_source_with_letters_spaced_apart(self):
        source = "M y object is to place beyond doubt th e existence of the hereditary transm ission of tw o-thirds"
        self.assertTrue(matches("My object is to place beyond doubt the existence", source))
        self.assertTrue(matches("the hereditary transmission of two-thirds", source))

    def test_quote_cannot_split_a_source_word(self):
        self.assertFalse(matches("he is a theist by temperament", "he is atheist by temperament"))

    def test_trailing_punctuation_in_quote(self):
        self.assertTrue(matches("it isn't the only factor.", self.SOURCE))

    def test_non_latin_quotes(self):
        self.assertTrue(matches("Το πρώτο αποτέλεσμα",
                                "Περίληψη. Το πρώτο "
                                "αποτέλεσμα είναι σαφές."))
        self.assertFalse(matches("πρώτο αποτέλ", "πρώτο αποτέλεσμα"))
        self.assertTrue(matches("重要的结果", "这是一个重要的结果。"))


class GalleryStillValidates(unittest.TestCase):
    def test_every_gallery_lesson_passes_every_check(self):
        for entry in server.gallery_index():
            with self.subTest(slug=entry["slug"]):
                lesson, source = server.load_gallery(entry["slug"])
                self.assertIsNotNone(source)
                self.assertEqual(list(L.check_lesson(lesson, source)), [])

    def test_bundled_example_passes_every_check(self):
        lesson, source = server.load_example()
        self.assertEqual(list(L.check_lesson(lesson, source)), [])


if __name__ == "__main__":
    unittest.main()
