from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from douyin_pipeline.telegram_messages import (
    build_failure_manifest_text,
    build_failure_text,
    build_help_text,
    build_job_started_text,
    build_mode_expired_text,
    build_mode_selection_text,
    build_public_links,
    build_success_summary_text,
    build_summary_document_caption,
    build_summary_expired_text,
    build_summary_failed_text,
    build_summary_selection_text,
    build_summary_skipped_text,
    build_summary_started_text,
    build_transcript_caption,
    build_web_missing_text,
    format_clock,
    phase_progress_message,
    resolve_transcript_file,
    split_message_chunks,
    transcribing_progress_message,
    truncate_text,
)


class TelegramMessagesTests(unittest.TestCase):
    def test_help_text_is_chinese_and_mentions_supported_sites(self) -> None:
        text = build_help_text()

        self.assertIn("抖音", text)
        self.assertIn("小红书", text)
        self.assertIn("/help", text)
        self.assertIn("先让你选择处理模式", text)

    def test_build_web_missing_text_is_chinese(self) -> None:
        self.assertEqual(build_web_missing_text(), "网页地址还没有配置。")

    def test_build_mode_selection_text_is_actionable(self) -> None:
        text = build_mode_selection_text()

        self.assertIn("快速转写", text)
        self.assertIn("高精度转写", text)
        self.assertIn("只下载视频", text)

    def test_build_mode_expired_text_is_chinese(self) -> None:
        self.assertEqual(build_mode_expired_text(), "这个选择已经失效了，请重新发送一次链接。")

    def test_build_job_started_text_mentions_mode(self) -> None:
        text = build_job_started_text("job-1", mode_label="高精度转写", action="run")
        self.assertIn("高精度转写", text)
        self.assertIn("正在下载并转写", text)

        download_text = build_job_started_text("job-2", mode_label="只下载视频", action="download")
        self.assertIn("只下载视频", download_text)
        self.assertIn("正在下载视频", download_text)

    def test_build_summary_messages_are_chinese(self) -> None:
        selection_text = build_summary_selection_text("job-1")
        self.assertIn("要不要继续做总结", selection_text)
        self.assertIn("job-1", selection_text)
        self.assertEqual(build_summary_expired_text(), "这个总结选项已经失效了，请重新发送一条链接。")
        self.assertEqual(build_summary_started_text("job-1", "通用"), "已开始总结。\n任务 ID：job-1\n风格：通用")
        self.assertEqual(build_summary_skipped_text("job-1"), "已跳过总结。\n任务 ID：job-1")
        self.assertEqual(build_summary_failed_text("通用", "超时"), "通用总结失败。\n原因：超时")
        self.assertEqual(build_summary_document_caption("job-1", "通用"), "通用总结 - job-1")

    def test_build_failure_text_appends_hint(self) -> None:
        self.assertEqual(build_failure_text("下载失败", "检查链接"), "下载失败\n建议：检查链接")
        self.assertEqual(build_failure_text("下载失败", None), "下载失败")

    def test_build_failure_manifest_text_formats_error_and_hint(self) -> None:
        text = build_failure_manifest_text(
            {
                "job_id": "job-1",
                "error": "下载失败",
                "error_hint": "重试",
            }
        )

        self.assertIn("任务失败。", text)
        self.assertIn("job-1", text)
        self.assertIn("原因：下载失败", text)
        self.assertIn("建议：重试", text)

    def test_build_success_summary_text_includes_title_and_links(self) -> None:
        text = build_success_summary_text(
            {
                "job_id": "job-1",
                "title": "demo",
                "files": [{"label": "Video", "url": "/output/job-1/demo.mp4"}],
            },
            "http://127.0.0.1:4444",
        )

        self.assertIn("任务完成。", text)
        self.assertIn("标题：demo", text)
        self.assertIn("视频: http://127.0.0.1:4444/output/job-1/demo.mp4", text)

    def test_build_public_links_uses_chinese_labels(self) -> None:
        links = build_public_links(
            {
                "files": [
                    {"label": "Video", "url": "/video"},
                    {"label": "Audio", "url": "/audio"},
                    {"label": "Transcript", "url": "/text"},
                    {"label": "Summary", "url": "/summary"},
                ]
            },
            "http://host",
        )

        self.assertEqual(
            links,
            [
                "视频: http://host/video",
                "音频: http://host/audio",
                "文本: http://host/text",
                "总结: http://host/summary",
            ],
        )

    def test_truncate_text_adds_ellipsis(self) -> None:
        self.assertEqual(truncate_text("abcdef", 4), "abcd...")
        self.assertEqual(truncate_text("abc", 4), "abc")

    def test_split_message_chunks_prefers_newlines(self) -> None:
        chunks = split_message_chunks("第一段\n第二段\n第三段", limit=5)
        self.assertEqual(chunks, ["第一段", "第二段", "第三段"])

    def test_phase_progress_message_formats_known_phase(self) -> None:
        text = phase_progress_message({"phase": "loading_model", "job_id": "job-1"})

        self.assertEqual(text, "音频已准备，开始加载转写模型。\n任务 ID：job-1")

    def test_transcribing_progress_message_formats_eta_and_duration(self) -> None:
        text = transcribing_progress_message(
            {
                "job_id": "job-1",
                "processed_seconds": 42.0,
                "duration_seconds": 120.0,
                "eta_seconds": 18.0,
            },
            68.0,
        )

        self.assertIn("转写进度 68%", text)
        self.assertIn("已处理：0:42 / 2:00", text)
        self.assertIn("预计剩余：0:18", text)

    def test_format_clock_formats_hours_and_minutes(self) -> None:
        self.assertEqual(format_clock(42), "0:42")
        self.assertEqual(format_clock(3723), "1:02:03")

    def test_resolve_transcript_file_returns_existing_path(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            transcript = root / "job-1" / "demo.txt"
            transcript.parent.mkdir(parents=True)
            transcript.write_text("hello", encoding="utf-8")

            actual = resolve_transcript_file(root, "job-1/demo.txt")

        self.assertEqual(actual, transcript)

    def test_build_transcript_caption_is_chinese(self) -> None:
        self.assertEqual(build_transcript_caption("job-1"), "转写文本 - job-1")


if __name__ == "__main__":
    unittest.main()
