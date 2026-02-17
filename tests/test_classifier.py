import unittest
from pathlib import Path

import coursera_free_filter as cff


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class TestClassifier(unittest.TestCase):
    def _read_fixture(self, name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    def test_truly_free_fixture(self) -> None:
        html = self._read_fixture("sample_truly_free.html")
        classification, reason = cff.classify_html(html)
        self.assertEqual(classification, cff.CLASS_TRULY_FREE)
        self.assertIn("no reject phrases", reason.lower())

    def test_paid_preview_fixture(self) -> None:
        html = self._read_fixture("sample_paid_preview.html")
        classification, reason = cff.classify_html(html)
        self.assertEqual(classification, cff.CLASS_PAID_OR_PREVIEW)
        self.assertIn("reject phrase", reason.lower())

    def test_unknown_fixture(self) -> None:
        html = self._read_fixture("sample_unknown.html")
        classification, _reason = cff.classify_html(html)
        self.assertEqual(classification, cff.CLASS_UNKNOWN)

    def test_enroll_plus_no_certificate_is_truly_free(self) -> None:
        html = "<button>Enroll for free</button><div>No Certificate</div>"
        classification, _reason = cff.classify_html(html)
        self.assertEqual(classification, cff.CLASS_TRULY_FREE)

    def test_payment_dollar_context_rejects(self) -> None:
        html = "<p>Only $39 per month with full access.</p>"
        classification, _reason = cff.classify_html(html)
        self.assertEqual(classification, cff.CLASS_PAID_OR_PREVIEW)

    def test_non_payment_dollar_without_context_does_not_auto_reject(self) -> None:
        html = "<p>You could save $100 in effort with this training.</p>"
        classification, _reason = cff.classify_html(html)
        self.assertEqual(classification, cff.CLASS_UNKNOWN)

    def test_reject_phrase_overrides_truly_free_signals(self) -> None:
        html = "<div>Full Course, No Certificate</div><button>Preview this course</button>"
        classification, _reason = cff.classify_html(html)
        self.assertEqual(classification, cff.CLASS_PAID_OR_PREVIEW)


if __name__ == "__main__":
    unittest.main()
