import unittest

import coursera_free_filter as cff


class TestExtractor(unittest.TestCase):
    def test_normalize_url_removes_tracking_params(self) -> None:
        url = (
            "https://www.coursera.org/learn/machine-learning"
            "?utm_source=newsletter&gclid=abc123&keep=yes#section"
        )
        normalized = cff.normalize_url(url)
        self.assertEqual(normalized, "https://coursera.org/learn/machine-learning?keep=yes")

    def test_normalize_url_resolves_relative(self) -> None:
        normalized = cff.normalize_url("/learn/python?utm_medium=email", base_url="https://www.coursera.org")
        self.assertEqual(normalized, "https://coursera.org/learn/python")

    def test_extract_course_urls_filters_and_dedupes(self) -> None:
        html = """
        <html><body>
          <a href="https://www.coursera.org/learn/python-for-everybody?utm_source=test">Course A</a>
          <a href="/specializations/data-science">Specialization</a>
          <a href="https://coursera.org/professional-certificates/google-it-support?fbclid=1">Cert</a>
          <a href="https://www.coursera.org/learn/python-for-everybody">Course A duplicate</a>
          <a href="https://www.coursera.org/projects/some-guided-project">Ignore project</a>
          <a href="https://example.com/learn/not-coursera">Ignore external</a>
        </body></html>
        """
        urls = cff.extract_course_urls_from_html(html)
        self.assertEqual(
            urls,
            [
                "https://coursera.org/learn/python-for-everybody",
                "https://coursera.org/specializations/data-science",
                "https://coursera.org/professional-certificates/google-it-support",
            ],
        )

    def test_extract_course_url_from_course_html_prefers_canonical(self) -> None:
        html = """
        <html>
          <head>
            <link rel="canonical" href="https://www.coursera.org/learn/deep-learning?utm_campaign=x" />
          </head>
          <body>
            <a href="https://www.coursera.org/learn/another-course">Other</a>
          </body>
        </html>
        """
        url = cff.extract_course_url_from_course_html(html)
        self.assertEqual(url, "https://coursera.org/learn/deep-learning")

    def test_extract_course_url_strict_meta_does_not_use_listing_links(self) -> None:
        html = """
        <html>
          <head>
            <link rel="canonical" href="https://www.coursera.org/search?query=python" />
          </head>
          <body>
            <a href="https://www.coursera.org/learn/python-for-everybody">Course</a>
          </body>
        </html>
        """
        strict_url = cff.extract_course_url_from_course_html(html, strict_meta=True)
        loose_url = cff.extract_course_url_from_course_html(html, strict_meta=False)
        self.assertIsNone(strict_url)
        self.assertEqual(loose_url, "https://coursera.org/learn/python-for-everybody")

    def test_is_coursera_course_url(self) -> None:
        self.assertTrue(cff.is_coursera_course_url("https://coursera.org/learn/abc"))
        self.assertFalse(cff.is_coursera_course_url("https://coursera.org/projects/abc"))
        self.assertFalse(cff.is_coursera_course_url("https://example.com/learn/abc"))


if __name__ == "__main__":
    unittest.main()
