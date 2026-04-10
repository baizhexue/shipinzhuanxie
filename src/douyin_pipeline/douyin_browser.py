from __future__ import annotations

import html
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
from typing import Optional

from douyin_pipeline.downloader import DownloadResult
from douyin_pipeline.subprocess_utils import run_command


DOUYIN_VIDEO_ID_PATTERN = re.compile(r"/video/(?P<id>\d+)")
DOUYIN_BROWSER_FALLBACK_TIMEOUT_SECONDS = 150
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_RETRY_ATTEMPTS = 2
logger = logging.getLogger(__name__)
CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
)


def download_with_browser(
    source_url: str,
    job_dir: Path,
) -> DownloadResult:
    command = [
        sys.executable,
        "-c",
        _build_worker_script(),
        source_url,
        str(job_dir),
    ]
    try:
        completed = run_command(
            command,
            timeout=DOUYIN_BROWSER_FALLBACK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Douyin browser fallback timed out.\n"
            f"stderr: browser fallback exceeded {DOUYIN_BROWSER_FALLBACK_TIMEOUT_SECONDS} seconds"
        ) from exc

    if completed.returncode != 0:
        raise RuntimeError(
            "Douyin browser fallback failed.\n"
            f"stderr: {completed.stderr.strip()}"
        )

    payload = _parse_worker_payload(completed.stdout)
    return DownloadResult(
        source_url=str(payload["source_url"]),
        title=str(payload["title"]),
        video_path=Path(str(payload["video_path"])),
        job_dir=Path(str(payload["job_dir"])),
    )


def _download_with_browser_inner(
    source_url: str,
    job_dir: Path,
) -> DownloadResult:
    detail = _fetch_detail_in_browser(source_url)
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


def _fetch_detail_in_browser(source_url: str) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Browser fallback requires `playwright`. Run: pip install playwright"
        ) from exc

    executable = _discover_chrome_executable()
    with sync_playwright() as playwright:
        launch_kwargs = {
            "headless": True,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if executable:
            launch_kwargs["executable_path"] = str(executable)

        browser = playwright.chromium.launch(**launch_kwargs)
        context = None
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(5000)
            page_html = page.content()
            match = DOUYIN_VIDEO_ID_PATTERN.search(page.url)
            if not match:
                fallback_detail = _extract_detail_from_html(page_html, page.url)
                if fallback_detail is not None:
                    return fallback_detail
                raise RuntimeError(f"Unable to resolve Douyin video id from URL: {page.url}")

            aweme_id = match.group("id")
            api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={aweme_id}"
            detail_payload = page.evaluate(
                """
                async (url) => {
                  const controller = new AbortController();
                  const timer = setTimeout(() => controller.abort(), 30000);
                  try {
                    const response = await fetch(url, {
                      credentials: 'include',
                      signal: controller.signal,
                    });
                    return await response.json();
                  } finally {
                    clearTimeout(timer);
                  }
                }
                """,
                api_url,
            )
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            browser.close()

    detail = detail_payload.get("aweme_detail")
    if not isinstance(detail, dict):
        fallback_detail = _extract_detail_from_html(page_html, page.url)
        if fallback_detail is not None:
            return fallback_detail
        raise RuntimeError("Browser fallback could not fetch Douyin detail JSON.")
    return detail


def _extract_detail_from_html(page_html: str, page_url: str) -> Optional[dict]:
    match = DOUYIN_VIDEO_ID_PATTERN.search(page_url)
    aweme_id = match.group("id") if match else "unknown"
    title = _extract_title_from_html(page_html) or f"douyin_{aweme_id}"
    video_urls = _extract_video_urls_from_html(page_html)
    if not video_urls:
        return None
    return {
        "aweme_id": aweme_id,
        "desc": title,
        "video": {
            "play_addr": {
                "url_list": video_urls,
            }
        },
    }


def _extract_title_from_html(page_html: str) -> Optional[str]:
    patterns = (
        r'<meta\s+property="og:title"\s+content="([^"]+)"',
        r"<title>([^<]+)</title>",
    )
    for pattern in patterns:
        match = re.search(pattern, page_html, re.IGNORECASE)
        if match:
            value = html.unescape(match.group(1)).strip()
            if value:
                return value
    return None


def _extract_video_urls_from_html(page_html: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    decoded_html = html.unescape(page_html).replace("\\u002F", "/")
    for segment in decoded_html.split("https://")[1:]:
        candidate = ("https://" + segment).split()[0].split("<", 1)[0]
        if "/aweme/v1/play/" not in candidate and "douyinvod" not in candidate:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _select_video_url(detail: dict) -> str:
    video = detail.get("video") or {}
    for key in ("play_addr", "play_addr_h264", "play_addr_265", "download_addr"):
        candidate = (video.get(key) or {}).get("url_list") or []
        if candidate:
            return str(candidate[0])
    raise RuntimeError("Douyin detail JSON did not contain a playable video URL.")


def _download_file(url: str, destination: Path, *, referer: str) -> None:
    temp_path = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, DOWNLOAD_RETRY_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": referer,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response, temp_path.open("wb") as handle:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
            temp_path.replace(destination)
            return
        except Exception:
            temp_path.unlink(missing_ok=True)
            if attempt >= DOWNLOAD_RETRY_ATTEMPTS:
                raise
            logger.warning(
                "douyin browser file download retrying attempt=%s url=%s destination=%s",
                attempt + 1,
                url,
                destination,
            )


def _discover_chrome_executable() -> Optional[Path]:
    for candidate in CHROME_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _build_worker_script() -> str:
    return (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from douyin_pipeline.douyin_browser import _download_with_browser_inner\n"
        "result = _download_with_browser_inner(sys.argv[1], Path(sys.argv[2]))\n"
        "print(json.dumps({"
        "'source_url': result.source_url, "
        "'title': result.title, "
        "'video_path': str(result.video_path), "
        "'job_dir': str(result.job_dir)"
        "}, ensure_ascii=False))\n"
    )


def _parse_worker_payload(stdout: str) -> dict:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Douyin browser fallback returned empty output.")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Douyin browser fallback returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Douyin browser fallback returned invalid payload.")
    return payload


if __name__ == "__main__":
    inner_result = _download_with_browser_inner(sys.argv[1], Path(sys.argv[2]))
    print(
        json.dumps(
            {
                "source_url": inner_result.source_url,
                "title": inner_result.title,
                "video_path": str(inner_result.video_path),
                "job_dir": str(inner_result.job_dir),
            },
            ensure_ascii=False,
        )
    )
