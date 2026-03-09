from __future__ import annotations

import unittest

from douyin_pipeline.errors import classify_exception


class ErrorClassificationTests(unittest.TestCase):
    def test_classifies_douyin_cookie_error(self) -> None:
        error = RuntimeError("Video download failed.\nstderr: Fresh cookies (not necessarily logged in) are needed")
        actual = classify_exception(error)
        self.assertEqual(actual.code, "douyin_fresh_cookies")
        self.assertEqual(actual.kind, "auth")
        self.assertIn("cookies", actual.message)
        self.assertIsNotNone(actual.hint)

    def test_classifies_invalid_input(self) -> None:
        actual = classify_exception(ValueError("No URL found. Please paste the full share text or a URL."))
        self.assertEqual(actual.code, "invalid_input")
        self.assertEqual(actual.kind, "input")
        self.assertIn("YouTube", actual.hint)

    def test_falls_back_to_unknown_error(self) -> None:
        actual = classify_exception(RuntimeError("something unexpected"))
        self.assertEqual(actual.code, "unknown_error")
        self.assertEqual(actual.kind, "unknown")

    def test_classifies_unmerged_adaptive_streams(self) -> None:
        actual = classify_exception(
            RuntimeError(
                "Adaptive streams were downloaded but not merged into a playable file. "
                "yt-dlp needs ffmpeg access to assemble Bilibili-style video and audio streams."
            )
        )
        self.assertEqual(actual.code, "ffmpeg_merge_required")
        self.assertEqual(actual.kind, "dependency")
        self.assertIn("ffmpeg", actual.hint)

    def test_classifies_xiaohongshu_verification(self) -> None:
        actual = classify_exception(
            RuntimeError("Xiaohongshu page requires verification before the video can be accessed.")
        )
        self.assertEqual(actual.code, "xiaohongshu_verification_required")
        self.assertEqual(actual.kind, "auth")

    def test_classifies_xiaohongshu_video_url_missing(self) -> None:
        actual = classify_exception(
            RuntimeError("Xiaohongshu page did not expose a playable video URL.")
        )
        self.assertEqual(actual.code, "xiaohongshu_video_url_missing")
        self.assertEqual(actual.kind, "download")

    def test_classifies_kuaishou_non_video(self) -> None:
        actual = classify_exception(
            RuntimeError("Kuaishou share is not a video. photoType=PHOTO")
        )
        self.assertEqual(actual.code, "kuaishou_non_video")
        self.assertEqual(actual.kind, "input")

    def test_classifies_kuaishou_video_url_missing(self) -> None:
        actual = classify_exception(
            RuntimeError("Kuaishou page did not expose a playable video URL.")
        )
        self.assertEqual(actual.code, "kuaishou_video_url_missing")
        self.assertEqual(actual.kind, "download")


if __name__ == "__main__":
    unittest.main()
