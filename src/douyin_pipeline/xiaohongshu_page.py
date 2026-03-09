from __future__ import annotations

from html import unescape
from pathlib import Path
import json
import re
import urllib.request

from douyin_pipeline.downloader import DownloadResult


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/142.0.0.0 Safari/537.36"
)
OG_VIDEO_PATTERN = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:video["\'][^>]+content=["\'](?P<content>[^"\']+)["\']',
    re.IGNORECASE,
)
OG_TITLE_PATTERN = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]+content=["\'](?P<content>[^"\']+)["\']',
    re.IGNORECASE,
)
TITLE_TAG_PATTERN = re.compile(r"<title>(?P<content>.*?)</title>", re.IGNORECASE | re.DOTALL)
MASTER_URL_PATTERN = re.compile(r'"masterUrl":"(?P<content>[^"]+)"')
STATE_TITLE_PATTERN = re.compile(r'"title":"(?P<content>[^"]+)"')
NOTE_ID_PATTERN = re.compile(r"/discovery/item/(?P<id>[0-9a-zA-Z]+)")


def download_with_page(
    source_url: str,
    job_dir: Path,
) -> DownloadResult:
    resolved_url, html = _fetch_page(source_url)
    note_id = _extract_note_id(resolved_url) or "xiaohongshu"
    title = _extract_title(html) or f"xiaohongshu_{note_id}"
    video_url = _extract_video_url(html)
    video_path = job_dir / f"xiaohongshu_{note_id}.mp4"

    _download_file(video_url, video_path, referer=resolved_url)

    (job_dir / "xiaohongshu_detail.json").write_text(
        json.dumps(
            {
                "resolved_url": resolved_url,
                "note_id": note_id,
                "title": title,
                "video_url": video_url,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return DownloadResult(
        source_url=resolved_url,
        title=title,
        video_path=video_path,
        job_dir=job_dir,
    )


def _fetch_page(source_url: str) -> tuple[str, str]:
    request = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        resolved_url = response.geturl()
        html = response.read().decode("utf-8", errors="ignore")
    return resolved_url, html


def _extract_note_id(resolved_url: str) -> str | None:
    match = NOTE_ID_PATTERN.search(resolved_url)
    if not match:
        return None
    return match.group("id")


def _extract_title(html: str) -> str | None:
    meta_title = _match_content(OG_TITLE_PATTERN, html)
    if meta_title:
        return meta_title

    title_tag = _match_content(TITLE_TAG_PATTERN, html)
    if title_tag:
        return title_tag.replace(" - 小红书", "").strip()

    state_title = _match_json_string(STATE_TITLE_PATTERN, html)
    if state_title:
        return state_title

    return None


def _extract_video_url(html: str) -> str:
    meta_video = _match_content(OG_VIDEO_PATTERN, html)
    if meta_video:
        return _normalize_url(meta_video)

    state_video = _match_json_string(MASTER_URL_PATTERN, html)
    if state_video:
        return _normalize_url(state_video)

    if "captcha" in html.lower() or "访问验证" in html:
        raise RuntimeError("Xiaohongshu page requires verification before the video can be accessed.")

    raise RuntimeError("Xiaohongshu page did not expose a playable video URL.")


def _match_content(pattern: re.Pattern[str], html: str) -> str | None:
    match = pattern.search(html)
    if not match:
        return None
    return unescape(match.group("content")).strip()


def _match_json_string(pattern: re.Pattern[str], html: str) -> str | None:
    match = pattern.search(html)
    if not match:
        return None
    return json.loads(f'"{match.group("content")}"')


def _normalize_url(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("http://"):
        return "https://" + normalized[len("http://") :]
    return normalized


def _download_file(url: str, destination: Path, *, referer: str) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": referer,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
