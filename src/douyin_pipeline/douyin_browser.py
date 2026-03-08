from __future__ import annotations

from pathlib import Path
import json
import re
import shutil
import urllib.request
from typing import Optional

from douyin_pipeline.downloader import DownloadResult


DOUYIN_VIDEO_ID_PATTERN = re.compile(r"/video/(?P<id>\d+)")
CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)


def download_with_browser(
    source_url: str,
    job_dir: Path,
) -> DownloadResult:
    detail = _fetch_detail_in_browser(source_url, job_dir)
    aweme_id = str(detail["aweme_id"])
    video_url = _select_video_url(detail)
    title = str(detail.get("desc") or f"douyin_{aweme_id}")
    video_path = job_dir / f"douyin_{aweme_id}.mp4"

    _download_file(
        video_url,
        video_path,
        referer=f"https://www.douyin.com/video/{aweme_id}",
    )

    (job_dir / "douyin_detail.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return DownloadResult(
        source_url=source_url,
        title=title,
        video_path=video_path,
        job_dir=job_dir,
    )


def _fetch_detail_in_browser(source_url: str, job_dir: Path) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Browser fallback requires `playwright`. Run: pip install playwright"
        ) from exc

    profile_dir = job_dir / "_browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    executable = _discover_chrome_executable()

    with sync_playwright() as playwright:
        kwargs = {
            "user_data_dir": str(profile_dir),
            "headless": True,
            "args": ["--disable-blink-features=AutomationControlled"],
            "viewport": {"width": 1440, "height": 900},
        }
        if executable:
            kwargs["executable_path"] = str(executable)
        else:
            kwargs["channel"] = "chrome"

        browser = playwright.chromium.launch_persistent_context(**kwargs)
        try:
            page = browser.new_page()
            page.goto(source_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(10000)
            match = DOUYIN_VIDEO_ID_PATTERN.search(page.url)
            if not match:
                raise RuntimeError(f"Unable to resolve Douyin video id from URL: {page.url}")

            aweme_id = match.group("id")
            api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={aweme_id}"
            detail_payload = page.evaluate(
                """
                async (url) => {
                  const response = await fetch(url, { credentials: 'include' });
                  return await response.json();
                }
                """,
                api_url,
            )
        finally:
            browser.close()
            shutil.rmtree(profile_dir, ignore_errors=True)

    detail = detail_payload.get("aweme_detail")
    if not isinstance(detail, dict):
        raise RuntimeError("Browser fallback could not fetch Douyin detail JSON.")
    return detail


def _select_video_url(detail: dict) -> str:
    video = detail.get("video") or {}
    for key in ("play_addr", "play_addr_h264", "play_addr_265", "download_addr"):
        candidate = (video.get(key) or {}).get("url_list") or []
        if candidate:
            return str(candidate[0])
    raise RuntimeError("Douyin detail JSON did not contain a playable video URL.")


def _download_file(url: str, destination: Path, *, referer: str) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": referer,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def _discover_chrome_executable() -> Optional[Path]:
    for candidate in CHROME_CANDIDATES:
        if candidate.exists():
            return candidate
    return None
