from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from douyin_pipeline.config import Settings
from douyin_pipeline.transcriber import (
    _build_transcribe_options,
    _create_whisper_model,
    _run_transcription_with_fallback,
)


class WhisperRuntimeFallbackTests(unittest.TestCase):
    def _make_settings(self, device: str) -> Settings:
        return Settings(
            output_dir=Path('.').resolve(),
            cookies_file=None,
            cookies_from_browser=None,
            ffmpeg_cmd=('ffmpeg',),
            ytdlp_cmd=('yt-dlp',),
            whisper_model='small',
            whisper_device=device,
            openclaw_token=None,
        )

    def test_auto_device_falls_back_to_cpu_when_cuda_runtime_missing(self) -> None:
        calls = []

        class FakeWhisperModel:
            def __init__(self, model_name, device):
                calls.append((model_name, device))
                if device == 'auto':
                    raise RuntimeError('Library cublas64_12.dll is not found or cannot be loaded')
                self.device = device

        fake_module = SimpleNamespace(WhisperModel=FakeWhisperModel)
        with patch.dict(sys.modules, {'faster_whisper': fake_module}):
            model = _create_whisper_model(self._make_settings('auto'))

        self.assertEqual(calls, [('small', 'auto'), ('small', 'cpu')])
        self.assertEqual(model.device, 'cpu')

    def test_explicit_device_error_is_not_silently_retried(self) -> None:
        class FakeWhisperModel:
            def __init__(self, model_name, device):
                raise RuntimeError('CUDA failed with error unknown')

        fake_module = SimpleNamespace(WhisperModel=FakeWhisperModel)
        with patch.dict(sys.modules, {'faster_whisper': fake_module}):
            with self.assertRaises(RuntimeError):
                _create_whisper_model(self._make_settings('cuda'))

    def test_transcribe_call_falls_back_to_cpu_when_auto_runtime_fails(self) -> None:
        class BrokenAutoModel:
            def transcribe(self, *args, **kwargs):
                raise RuntimeError('Library cublas64_12.dll is not found or cannot be loaded')

        class CpuModel:
            def transcribe(self, *args, **kwargs):
                return ([], SimpleNamespace(duration=0.0, language='zh'))

        with patch(
            'douyin_pipeline.transcriber._create_whisper_model',
            side_effect=[BrokenAutoModel(), CpuModel()],
        ) as mocked_factory:
            segments, info = _run_transcription_with_fallback(
                Path('demo.wav'),
                self._make_settings('auto'),
            )

        self.assertEqual(list(segments), [])
        self.assertEqual(info.language, 'zh')
        self.assertEqual(mocked_factory.call_args_list[0].args[0].whisper_device, 'auto')
        self.assertEqual(mocked_factory.call_args_list[1].args[0].whisper_device, 'cpu')

    def test_build_transcribe_options_uses_beam_search_defaults(self) -> None:
        options = _build_transcribe_options(self._make_settings('cpu'))

        self.assertEqual(options['beam_size'], 5)
        self.assertEqual(options['vad_filter'], True)
        self.assertNotIn('language', options)
        self.assertNotIn('initial_prompt', options)

    def test_build_transcribe_options_adds_language_hint_and_prompt(self) -> None:
        settings = Settings(
            output_dir=Path('.').resolve(),
            cookies_file=None,
            cookies_from_browser=None,
            ffmpeg_cmd=('ffmpeg',),
            ytdlp_cmd=('yt-dlp',),
            whisper_model='medium',
            whisper_device='cpu',
            openclaw_token=None,
            whisper_language='zh',
            whisper_beam_size=6,
        )

        options = _build_transcribe_options(settings)

        self.assertEqual(options['beam_size'], 6)
        self.assertEqual(options['language'], 'zh')
        self.assertIn('简体中文', options['initial_prompt'])


if __name__ == '__main__':
    unittest.main()
