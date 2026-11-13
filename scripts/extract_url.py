#!/usr/bin/env python3
"""从分享口令或任意文本中抽出第一个 URL（按出现顺序）。没有则退出码 0 且不打印。

URL 只由 RFC 3986 允许的 ASCII 字符组成：遇到中文、全角标点、空白等任何
非 ASCII 字符就截断，再去掉末尾的英文标点。
"""
from __future__ import annotations

import re
import sys

# RFC 3986 允许出现在 URL 里的字符（不含 < > " ` 空白 和所有非 ASCII）
_URL_CHARS = r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]"

# 带 scheme 的 URL
SCHEME_RE = re.compile(r"(?i)https?://" + _URL_CHARS + r"+")

# 没写 scheme 的已知平台链接。host 前面不能紧贴 ASCII 字母数字、点或连字符，
# 这样「复制链接v.douyin.com/…」里的中文不会并进 host。
HOST_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9.\-/])((?:www\.)?(?:"
    r"v\.douyin\.com|iesdouyin\.com|(?:[A-Za-z0-9-]+\.)?douyin\.com|"
    r"(?:[A-Za-z0-9-]+\.)?xiaohongshu\.com|xhslink\.com|"
    r"(?:[A-Za-z0-9-]+\.)?x\.com|(?:[A-Za-z0-9-]+\.)?twitter\.com|t\.co|"
    r"(?:[A-Za-z0-9-]+\.)?youtube\.com|youtu\.be|(?:[A-Za-z0-9-]+\.)?youtube-nocookie\.com|"
    r"mp\.weixin\.qq\.com|(?:[A-Za-z0-9-]+\.)?weixin\.qq\.com"
    r")/" + _URL_CHARS + r"*)"
)

TRAIL = ".,;:!?'\"*"
PAIRS = {")": "(", "]": "["}


def clean(u: str) -> str:
    u = u.strip()
    while u:
        last = u[-1]
        if last in TRAIL:
            u = u[:-1]
        elif last in PAIRS and u.count(last) > u.count(PAIRS[last]):
            # 去掉没有配对的右括号，例如「(见 https://x.com/a/status/1)」
            u = u[:-1]
        else:
            break
    return u


def extract_url(text: str) -> str:
    """返回文本中最早出现的 URL；带不带 scheme 都算。"""
    best: tuple[int, str] | None = None
    m = SCHEME_RE.search(text)
    if m:
        u = clean(m.group(0))
        if re.match(r"(?i)https?://.", u):
            best = (m.start(), u)
    m = HOST_RE.search(text)
    if m and (best is None or m.start() < best[0]):
        u = clean(m.group(1))
        if u:
            best = (m.start(), "https://" + u)
    return best[1] if best else ""


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    u = extract_url(text)
    if u:
        print(u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
