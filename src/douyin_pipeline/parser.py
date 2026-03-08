from __future__ import annotations

import re


URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?)]}\"'，。；：！？】）"


def extract_share_url(raw_text: str) -> str:
    match = URL_PATTERN.search(raw_text)
    if not match:
        raise ValueError("No URL found. Please paste the full share text or a URL.")

    return match.group(0).rstrip(TRAILING_PUNCTUATION)
