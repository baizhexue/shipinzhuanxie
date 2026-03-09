from __future__ import annotations

import unittest

from douyin_pipeline.xiaohongshu_page import _extract_title, _extract_video_url


HTML_SAMPLE = """
<html>
  <head>
    <meta property="og:title" content="大家忽视了北京户口的重要性" />
    <meta property="og:video" content="https://sns-video-hs.xhscdn.com/stream/demo.mp4" />
  </head>
  <body></body>
</html>
"""


class XiaoHongShuPageTests(unittest.TestCase):
    def test_extract_video_url_prefers_og_video(self) -> None:
        self.assertEqual(
            _extract_video_url(HTML_SAMPLE),
            "https://sns-video-hs.xhscdn.com/stream/demo.mp4",
        )

    def test_extract_title_prefers_meta_title(self) -> None:
        self.assertEqual(_extract_title(HTML_SAMPLE), "大家忽视了北京户口的重要性")


if __name__ == "__main__":
    unittest.main()
