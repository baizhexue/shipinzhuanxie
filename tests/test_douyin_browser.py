from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from douyin_pipeline.douyin_browser import (
    DOUYIN_BROWSER_FALLBACK_TIMEOUT_SECONDS,
    _extract_detail_from_html,
    _download_file,
    _extract_title_from_html,
    _extract_video_urls_from_html,
    _parse_worker_payload,
    download_with_browser,
)


class DouyinBrowserTests(unittest.TestCase):
    def test_download_file_streams_in_chunks(self) -> None:
        class FakeResponse:
            def __init__(self) -> None:
                self.read_sizes = []
                self._chunks = [b"hello ", b"world", b""]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size: int = -1) -> bytes:
                self.read_sizes.append(size)
                return self._chunks.pop(0)

        response = FakeResponse()
        with TemporaryDirectory() as tmp_dir:
            destination = Path(tmp_dir) / "demo.mp4"
            with patch("urllib.request.urlopen", return_value=response):
                _download_file("https://example.com/demo.mp4", destination, referer="https://www.douyin.com/video/demo")

            self.assertEqual(destination.read_bytes(), b"hello world")
            self.assertGreater(response.read_sizes[0], 0)

    def test_download_with_browser_times_out_cleanly(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch(
                "douyin_pipeline.douyin_browser.run_command",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["python", "-c", "pass"],
                    timeout=DOUYIN_BROWSER_FALLBACK_TIMEOUT_SECONDS,
                ),
            ):
                with self.assertRaises(RuntimeError) as context:
                    download_with_browser("https://v.douyin.com/demo/", Path(tmp_dir))

        self.assertIn("Douyin browser fallback timed out.", str(context.exception))

    def test_parse_worker_payload_uses_last_json_line(self) -> None:
        payload = _parse_worker_payload('log line\n{"title":"demo","source_url":"u","video_path":"v","job_dir":"j"}\n')
        self.assertEqual(payload["title"], "demo")

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
