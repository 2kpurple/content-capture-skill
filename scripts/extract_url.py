#!/usr/bin/env python3
"""从分享口令或任意文本中抽出第一个 URL。没有则退出码 0 且不打印。"""
from __future__ import annotations

import re
import sys

TRAIL = ".,;:!?。，、；：！？)]}>」』】》'\""
STOP = set("<>\"'`）)】]〉>")

HOST_RE = re.compile(
    r"(?i)(?:^|[\s　])((?:www\.)?(?:"
    r"v\.douyin\.com|iesdouyin\.com|(?:[\w-]+\.)?douyin\.com|"
    r"(?:[\w-]+\.)?xiaohongshu\.com|xhslink\.com|"
    r"(?:[\w-]+\.)?x\.com|(?:[\w-]+\.)?twitter\.com|t\.co|"
    r"(?:[\w-]+\.)?youtube\.com|youtu\.be|(?:[\w-]+\.)?youtube-nocookie\.com|"
    r"mp\.weixin\.qq\.com|(?:[\w-]+\.)?weixin\.qq\.com"
    r")/\S*)"
)


def clean(u: str) -> str:
    u = u.strip()
    while u and u[-1] in TRAIL:
        u = u[:-1]
    return u


def take_url(s: str, i: int = 0) -> str:
    j = i
    while j < len(s) and not s[j].isspace() and s[j] not in STOP:
        j += 1
    return clean(s[i:j])


def extract_url(text: str) -> str:
    low = text.lower()
    for key in ("https://", "http://"):
        i = low.find(key)
        if i >= 0:
            u = take_url(text, i)
            if u:
                return u
    m = HOST_RE.search(" " + text)
    if m:
        u = take_url(m.group(1), 0)
        if u:
            if not re.match(r"(?i)https?://", u):
                u = "https://" + u
            return u
    return ""


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    u = extract_url(text)
    if u:
        print(u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
