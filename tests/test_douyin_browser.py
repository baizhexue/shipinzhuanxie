from __future__ import annotations

import unittest

from douyin_pipeline.douyin_browser import (
    _extract_detail_from_html,
    _extract_title_from_html,
    _extract_video_urls_from_html,
)


class DouyinBrowserTests(unittest.TestCase):
    def test_extract_title_prefers_og_title(self) -> None:
        html = '<html><head><meta property="og:title" content="demo title" /></head></html>'
        self.assertEqual(_extract_title_from_html(html), "demo title")

    def test_extract_video_urls_unescapes_and_deduplicates(self) -> None:
        html = (
            '<html><body>'
            'https://v26-web.douyinvod.com/demo/video.mp4?a=1&amp;b=2 '
            'https://v26-web.douyinvod.com/demo/video.mp4?a=1&amp;b=2 '
            'https://www.douyin.com/aweme/v1/play/?file_id=demo&amp;is_play_url=1'
            '</body></html>'
        )
        self.assertEqual(
            _extract_video_urls_from_html(html),
            [
                "https://v26-web.douyinvod.com/demo/video.mp4?a=1&b=2",
                "https://www.douyin.com/aweme/v1/play/?file_id=demo&is_play_url=1",
            ],
        )

    def test_extract_detail_from_html_builds_playable_fallback_detail(self) -> None:
        html = (
            '<html><head><meta property="og:title" content="demo title" /></head>'
            '<body>'
            'https://v26-web.douyinvod.com/demo/video.mp4?a=1&amp;b=2'
            '</body></html>'
        )
        actual = _extract_detail_from_html(
            html,
            "https://www.douyin.com/video/7601401732534390043",
        )
        self.assertEqual(actual["aweme_id"], "7601401732534390043")
        self.assertEqual(actual["desc"], "demo title")
        self.assertEqual(
            actual["video"]["play_addr"]["url_list"],
            ["https://v26-web.douyinvod.com/demo/video.mp4?a=1&b=2"],
        )


if __name__ == "__main__":
    unittest.main()
