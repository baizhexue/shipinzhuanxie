from __future__ import annotations

from html import unescape
from pathlib import Path
import json
import re
import urllib.request
from typing import Any, Optional

from douyin_pipeline.downloader import DownloadResult


USER_AGENT = (
    "Mozilla/5.0"
)
INIT_STATE_PATTERN = re.compile(
    r"window\.INIT_STATE\s*=\s*(?P<payload>\{.*?\})\s*</script>",
    re.IGNORECASE | re.DOTALL,
)
PHOTO_PATH_PATTERN = re.compile(r"/fw/photo/(?P<id>[0-9a-zA-Z]+)")


def download_with_page(
    source_url: str,
    job_dir: Path,
) -> DownloadResult:
    resolved_url, html = _fetch_page(source_url)
    state = _extract_init_state(html)
    photo = _extract_photo_payload(state)
    photo_type = str(photo.get("photoType") or "").strip().upper()
    if photo_type and photo_type != "VIDEO":
        raise RuntimeError(f"Kuaishou share is not a video. photoType={photo_type}")

    photo_id = _extract_photo_id(resolved_url, photo)
    title = _extract_title(photo, photo_id)
    video_url = _extract_video_url(photo)
    video_path = job_dir / f"kuaishou_{photo_id}.mp4"

    _download_file(video_url, video_path, referer=resolved_url)

    (job_dir / "kuaishou_detail.json").write_text(
        json.dumps(
            {
                "resolved_url": resolved_url,
                "photo_id": photo_id,
                "title": title,
                "photo_type": photo_type or None,
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
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        resolved_url = response.geturl()
        html = response.read().decode("utf-8", errors="ignore")
    return resolved_url, html


def _extract_init_state(html: str) -> dict[str, Any]:
    match = INIT_STATE_PATTERN.search(html)
    if not match:
        raise RuntimeError("Kuaishou page did not expose INIT_STATE.")
    return json.loads(match.group("payload"))


def _extract_photo_payload(state: dict[str, Any]) -> dict[str, Any]:
    found = _find_photo_payload(state)
    if found is None:
        raise RuntimeError("Kuaishou page did not expose a share payload.")
    return found


def _find_photo_payload(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        photo = value.get("photo")
        if isinstance(photo, dict) and (
            photo.get("mainMvUrls")
            or photo.get("photoType")
            or photo.get("caption")
        ):
            return photo
        for child in value.values():
            found = _find_photo_payload(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_photo_payload(child)
            if found is not None:
                return found
    return None


def _extract_photo_id(resolved_url: str, photo: dict[str, Any]) -> str:
    photo_id = str(photo.get("photoId") or "").strip()
    if photo_id:
        return photo_id

    match = PHOTO_PATH_PATTERN.search(resolved_url)
    if match:
        return match.group("id")
    return "kuaishou"


def _extract_title(photo: dict[str, Any], photo_id: str) -> str:
    for key in ("caption", "userName"):
        candidate = str(photo.get(key) or "").strip()
        if candidate:
            return unescape(candidate).replace("\xa0", " ")
    return f"kuaishou_{photo_id}"


def _extract_video_url(photo: dict[str, Any]) -> str:
    main_urls = photo.get("mainMvUrls") or []
    if isinstance(main_urls, list):
        for item in main_urls:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("url") or "").strip()
            if candidate:
                return _normalize_url(candidate)

    raise RuntimeError("Kuaishou page did not expose a playable video URL.")


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
