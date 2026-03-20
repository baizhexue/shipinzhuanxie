from __future__ import annotations

from typing import Callable, Optional

from douyin_pipeline.parser import detect_source_platform


FallbackHandler = Callable[[str, object], object]


def resolve_download_fallback(source_url: str, error: RuntimeError) -> Optional[FallbackHandler]:
    platform = detect_source_platform(source_url)
    error_text = str(error).lower()

    if platform == "douyin" and _is_douyin_browser_fallback(error_text):
        return _download_with_douyin_browser
    if platform == "xiaohongshu":
        return _download_with_xiaohongshu_page
    if platform == "kuaishou":
        return _download_with_kuaishou_page
    return None


def _is_douyin_browser_fallback(error_text: str) -> bool:
    return "fresh cookies" in error_text or "timed out after" in error_text


def _download_with_douyin_browser(source_url: str, job_dir):
    from douyin_pipeline.douyin_browser import download_with_browser

    return download_with_browser(source_url, job_dir)


def _download_with_xiaohongshu_page(source_url: str, job_dir):
    from douyin_pipeline.xiaohongshu_page import download_with_page

    return download_with_page(source_url, job_dir)


def _download_with_kuaishou_page(source_url: str, job_dir):
    from douyin_pipeline.kuaishou_page import download_with_page

    return download_with_page(source_url, job_dir)
