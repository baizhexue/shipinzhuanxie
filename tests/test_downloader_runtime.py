from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import patch

from douyin_pipeline.downloader_runtime import (
    build_ytdlp_process_env,
    can_use_deno_compat_mode,
    detect_ytdlp_js_runtime,
    find_common_js_runtime_path,
    ytdlp_supports_js_runtimes,
)


class DownloaderRuntimeTests(unittest.TestCase):
    def test_detect_ytdlp_js_runtime_prefers_node_on_path(self) -> None:
        actual = detect_ytdlp_js_runtime(
            which=lambda name: "C:/node.exe" if name == "node" else None,
            home_factory=Path,
        )

        self.assertEqual(actual, "node")

    def test_detect_ytdlp_js_runtime_finds_deno_in_home(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            deno_bin = root / ".deno" / "bin" / "deno"
            deno_bin.parent.mkdir(parents=True)
            deno_bin.write_bytes(b"deno")

            actual = detect_ytdlp_js_runtime(
                which=lambda name: None,
                home_factory=lambda: root,
            )

        self.assertEqual(actual, f"deno:{deno_bin}")

    def test_find_common_js_runtime_path_returns_none_for_unknown_runtime(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            actual = find_common_js_runtime_path("bun", home_factory=lambda: Path(tmp_dir))

        self.assertIsNone(actual)

    def test_ytdlp_supports_js_runtimes_checks_help_output(self) -> None:
        with patch(
            "douyin_pipeline.downloader_runtime.run_command",
            return_value=SimpleNamespace(returncode=0, stdout="--js-runtimes", stderr=""),
        ) as mocked_run:
            actual = ytdlp_supports_js_runtimes(("yt-dlp",), timeout=8)

        self.assertTrue(actual)
        mocked_run.assert_called_once()

    def test_ytdlp_supports_js_runtimes_returns_false_on_timeout(self) -> None:
        with patch(
            "douyin_pipeline.downloader_runtime.run_command",
            side_effect=subprocess.TimeoutExpired(cmd=["yt-dlp", "--help"], timeout=8),
        ):
            actual = ytdlp_supports_js_runtimes(("yt-dlp",), timeout=8)

        self.assertFalse(actual)

    def test_can_use_deno_compat_mode_only_accepts_deno(self) -> None:
        self.assertTrue(can_use_deno_compat_mode("deno"))
        self.assertTrue(can_use_deno_compat_mode("deno:/tmp/deno"))
        self.assertFalse(can_use_deno_compat_mode("node"))

    def test_build_ytdlp_process_env_prepends_runtime_dir(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            deno_bin = root / "bin" / "deno"
            deno_bin.parent.mkdir(parents=True)
            deno_bin.write_bytes(b"deno")

            with patch.dict("os.environ", {"PATH": "C:/Windows/System32"}, clear=True):
                env = build_ytdlp_process_env(f"deno:{deno_bin}")

        self.assertIsNotNone(env)
        self.assertTrue(env["PATH"].startswith(str(deno_bin.parent)))


if __name__ == "__main__":
    unittest.main()
