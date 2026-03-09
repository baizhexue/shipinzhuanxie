from __future__ import annotations

import unittest
from unittest.mock import patch

from douyin_pipeline.doctor import _check_youtube_js_runtime


class DoctorTests(unittest.TestCase):
    def test_check_youtube_js_runtime_reports_missing(self) -> None:
        with patch("douyin_pipeline.doctor._detect_ytdlp_js_runtime", return_value=None):
            actual = _check_youtube_js_runtime(("yt-dlp",))

        self.assertFalse(actual.ok)
        self.assertIn("node or deno", actual.detail)

    def test_check_youtube_js_runtime_reports_detected_runtime(self) -> None:
        with patch(
            "douyin_pipeline.doctor._detect_ytdlp_js_runtime",
            return_value="deno:/Users/demo/.deno/bin/deno",
        ), patch(
            "douyin_pipeline.doctor._ytdlp_supports_js_runtimes",
            return_value=True,
        ):
            actual = _check_youtube_js_runtime(("yt-dlp",))

        self.assertTrue(actual.ok)
        self.assertIn("deno:", actual.detail)

    def test_check_youtube_js_runtime_reports_old_ytdlp(self) -> None:
        with patch(
            "douyin_pipeline.doctor._detect_ytdlp_js_runtime",
            return_value="node",
        ), patch(
            "douyin_pipeline.doctor._ytdlp_supports_js_runtimes",
            return_value=False,
        ):
            actual = _check_youtube_js_runtime(("yt-dlp",))

        self.assertFalse(actual.ok)
        self.assertIn("install deno or upgrade yt-dlp", actual.detail)

    def test_check_youtube_js_runtime_allows_old_ytdlp_with_deno(self) -> None:
        with patch(
            "douyin_pipeline.doctor._detect_ytdlp_js_runtime",
            return_value="deno:/Users/demo/.deno/bin/deno",
        ), patch(
            "douyin_pipeline.doctor._ytdlp_supports_js_runtimes",
            return_value=False,
        ):
            actual = _check_youtube_js_runtime(("yt-dlp",))

        self.assertTrue(actual.ok)
        self.assertIn("compat mode", actual.detail)


if __name__ == "__main__":
    unittest.main()
