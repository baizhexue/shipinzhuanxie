from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from douyin_pipeline.config import Settings
from douyin_pipeline.deepseek_summary import (
    SummaryError,
    get_summary_style_label,
    summarize_text,
    summarize_to_file,
)


def _make_settings(output_dir: Path) -> Settings:
    return Settings(
        output_dir=output_dir,
        cookies_file=None,
        cookies_from_browser=None,
        ffmpeg_cmd=("ffmpeg",),
        ytdlp_cmd=("yt-dlp",),
        whisper_model="medium",
        whisper_device="cpu",
        openclaw_token=None,
        deepseek_api_key="secret",
    )


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class DeepSeekSummaryTests(unittest.TestCase):
    def test_get_summary_style_label_rejects_invalid_style(self) -> None:
        with self.assertRaises(SummaryError):
            get_summary_style_label("invalid")

    def test_summarize_text_requires_api_key(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))
            settings = Settings(**{**settings.__dict__, "deepseek_api_key": None})
            with self.assertRaises(SummaryError):
                summarize_text("原文", style="general", settings=settings)

    def test_summarize_text_calls_deepseek_for_direct_prompt(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = _make_settings(Path(tmp_dir))
            captured_requests: list[dict] = []

            def _fake_urlopen(request, timeout):
                payload = json.loads(request.data.decode("utf-8"))
                captured_requests.append(payload)
                return _FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "总结结果",
                                }
                            }
                        ]
                    }
                )

            with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                actual = summarize_text("这是一段原文。", style="general", settings=settings)

        self.assertEqual(actual, "总结结果")
        self.assertEqual(captured_requests[0]["model"], "deepseek-chat")
        self.assertIn("原文如下", captured_requests[0]["messages"][1]["content"])

    def test_summarize_to_file_writes_markdown_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            settings = _make_settings(root)
            with patch(
                "urllib.request.urlopen",
                return_value=_FakeResponse(
                    {"choices": [{"message": {"content": "总结结果"}}]}
                ),
            ):
                result = summarize_to_file("原文", style="plain", job_dir=root, settings=settings)
                written_text = result.summary_path.read_text(encoding="utf-8").strip()

            self.assertEqual(result.text, "总结结果")
            self.assertTrue(result.summary_path.name.endswith("summary-plain.md"))
            self.assertEqual(written_text, "总结结果")


if __name__ == "__main__":
    unittest.main()
