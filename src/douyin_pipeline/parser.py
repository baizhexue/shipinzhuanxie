from __future__ import annotations

import re
from urllib.parse import urlparse


URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?)]}\"'\uFF0C\u3002\uFF1B\uFF1A\uFF01\uFF1F\u3011\uFF09"
PLATFORM_HOSTS = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "bilibili": ("bilibili.com", "b23.tv"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
    "kuaishou": ("kuaishou.com", "chenzhongtech.com"),
    "youtube": ("youtube.com", "youtu.be"),
}


def extract_share_url(raw_text: str) -> str:
    match = URL_PATTERN.search(raw_text)
    if not match:
        raise ValueError("No URL found. Please paste the full share text or a URL.")

    return match.group(0).rstrip(TRAILING_PUNCTUATION)


def detect_source_platform(source_url: str) -> str:
    host = urlparse(source_url).netloc.lower().split(":", 1)[0]
    for platform, domains in PLATFORM_HOSTS.items():
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return platform
    return "unknown"
