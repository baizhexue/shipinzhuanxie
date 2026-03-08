from __future__ import annotations

import unittest

from douyin_pipeline.transcriber import _normalize_transcript_text


class TranscriptNormalizationTests(unittest.TestCase):
    def test_converts_traditional_chinese_to_simplified(self) -> None:
        raw = "我後來發現這個影片裡面的資訊很完整"
        actual = _normalize_transcript_text(raw, detected_language="zh")
        self.assertEqual(actual, "我后来发现这个视频里面的信息很完整")

    def test_applies_small_mainland_term_mapping(self) -> None:
        raw = "這裡有下載連結，點開影片後用你的帳號登入。"
        actual = _normalize_transcript_text(raw, detected_language="zh")
        self.assertEqual(actual, "这里有下载链接，点开视频后用你的账号登录。")

    def test_skips_non_chinese_text(self) -> None:
        raw = "This is already English."
        actual = _normalize_transcript_text(raw, detected_language="en")
        self.assertEqual(actual, raw)


if __name__ == "__main__":
    unittest.main()
