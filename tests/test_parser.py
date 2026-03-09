from __future__ import annotations

import unittest

from douyin_pipeline.parser import detect_source_platform, extract_share_url


class ParserTests(unittest.TestCase):
    def test_extract_share_url_supports_xiaohongshu_share_text(self) -> None:
        raw_text = (
            "大家忽视了北京户口的重要性 http://xhslink.com/o/3gjd39CJOsa "
            "复制后打开【小红书】查看笔记！"
        )
        self.assertEqual(extract_share_url(raw_text), "http://xhslink.com/o/3gjd39CJOsa")

    def test_detect_source_platform_recognizes_xiaohongshu_short_link(self) -> None:
        self.assertEqual(detect_source_platform("http://xhslink.com/o/3gjd39CJOsa"), "xiaohongshu")

    def test_detect_source_platform_recognizes_kuaishou_short_link(self) -> None:
        self.assertEqual(detect_source_platform("https://v.kuaishou.com/Jw81AFy5"), "kuaishou")


if __name__ == "__main__":
    unittest.main()
