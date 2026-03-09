from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from douyin_pipeline.config import Settings
from douyin_pipeline.downloader import _download_with_ytdlp, _find_downloaded_video, download_video


class DownloaderTests(unittest.TestCase):
    def test_download_command_passes_ffmpeg_location_for_merge(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            job_dir = root / 'job-1'
            job_dir.mkdir()
            ffmpeg_bin = root / 'ffmpeg.exe'
            ffmpeg_bin.write_bytes(b'ffmpeg')
            settings = Settings(
                output_dir=root,
                cookies_file=None,
                cookies_from_browser=None,
                ffmpeg_cmd=(str(ffmpeg_bin),),
                ytdlp_cmd=('yt-dlp',),
                whisper_model='small',
                whisper_device='cpu',
            )

            def fake_run(command, capture_output, text, encoding, errors, check):
                self.assertIn('--merge-output-format', command)
                self.assertIn('mp4', command)
                self.assertIn('--ffmpeg-location', command)
                self.assertIn(str(ffmpeg_bin), command)
                self.assertNotIn('--restrict-filenames', command)
                (job_dir / 'demo.mp4').write_bytes(b'video')
                return SimpleNamespace(returncode=0, stdout='{"title": "demo"}\n', stderr='')

            with patch('douyin_pipeline.downloader.subprocess.run', side_effect=fake_run):
                result = _download_with_ytdlp('https://www.bilibili.com/video/BV1demo', settings, job_dir)

            self.assertEqual(result.title, 'demo')
            self.assertEqual(result.video_path.name, 'demo.mp4')
            self.assertTrue(result.video_path.exists())

    def test_youtube_download_uses_node_js_runtime_when_available(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            job_dir = root / 'job-1'
            job_dir.mkdir()
            ffmpeg_bin = root / 'ffmpeg.exe'
            ffmpeg_bin.write_bytes(b'ffmpeg')
            settings = Settings(
                output_dir=root,
                cookies_file=None,
                cookies_from_browser=None,
                ffmpeg_cmd=(str(ffmpeg_bin),),
                ytdlp_cmd=('yt-dlp',),
                whisper_model='small',
                whisper_device='cpu',
            )

            def fake_run(command, capture_output, text, encoding, errors, check):
                self.assertIn('--js-runtimes', command)
                runtime_index = command.index('--js-runtimes')
                self.assertEqual(command[runtime_index + 1], 'node')
                (job_dir / 'demo.mp4').write_bytes(b'video')
                return SimpleNamespace(returncode=0, stdout='{"title": "demo"}\n', stderr='')

            with patch('douyin_pipeline.downloader.shutil.which', side_effect=lambda name: 'C:/node.exe' if name == 'node' else None), patch(
                'douyin_pipeline.downloader.subprocess.run',
                side_effect=fake_run,
            ):
                result = _download_with_ytdlp('https://www.youtube.com/watch?v=Sdf8fc9b0mI', settings, job_dir)

        self.assertEqual(result.title, 'demo')
        self.assertEqual(result.video_path.name, 'demo.mp4')

    def test_find_downloaded_video_rejects_unmerged_adaptive_streams(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            job_dir = Path(tmp_dir)
            (job_dir / 'demo.f137.mp4').write_bytes(b'video-only')
            (job_dir / 'demo.f140.m4a').write_bytes(b'audio-only')

            with self.assertRaises(RuntimeError) as context:
                _find_downloaded_video(job_dir)

        self.assertIn('Adaptive streams were downloaded but not merged', str(context.exception))

    def test_download_video_falls_back_to_xiaohongshu_page_when_ytdlp_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            job_dir = root / 'job-1'
            job_dir.mkdir()
            settings = Settings(
                output_dir=root,
                cookies_file=None,
                cookies_from_browser=None,
                ffmpeg_cmd=('ffmpeg',),
                ytdlp_cmd=('yt-dlp',),
                whisper_model='small',
                whisper_device='cpu',
            )
            expected = SimpleNamespace(
                source_url='https://www.xiaohongshu.com/discovery/item/demo',
                title='demo',
                video_path=job_dir / 'demo.mp4',
                job_dir=job_dir,
            )

            with patch('douyin_pipeline.downloader._download_with_ytdlp', side_effect=RuntimeError('Video download failed.')), patch(
                'douyin_pipeline.xiaohongshu_page.download_with_page',
                return_value=expected,
            ) as fallback:
                actual = download_video('http://xhslink.com/o/demo', settings, job_dir=job_dir)

        self.assertEqual(actual.title, 'demo')
        fallback.assert_called_once()

    def test_download_video_falls_back_to_kuaishou_page_when_ytdlp_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            job_dir = root / 'job-1'
            job_dir.mkdir()
            settings = Settings(
                output_dir=root,
                cookies_file=None,
                cookies_from_browser=None,
                ffmpeg_cmd=('ffmpeg',),
                ytdlp_cmd=('yt-dlp',),
                whisper_model='small',
                whisper_device='cpu',
            )
            expected = SimpleNamespace(
                source_url='https://v.m.chenzhongtech.com/fw/photo/demo',
                title='demo',
                video_path=job_dir / 'demo.mp4',
                job_dir=job_dir,
            )

            with patch('douyin_pipeline.downloader._download_with_ytdlp', side_effect=RuntimeError('Video download failed.')), patch(
                'douyin_pipeline.kuaishou_page.download_with_page',
                return_value=expected,
            ) as fallback:
                actual = download_video('https://v.kuaishou.com/Jw81AFy5', settings, job_dir=job_dir)

        self.assertEqual(actual.title, 'demo')
        fallback.assert_called_once()


if __name__ == '__main__':
    unittest.main()
