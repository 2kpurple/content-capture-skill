#!/usr/bin/env python3
"""解析 TikTokDownloader 的 share/detail 响应，并按 data.downloads 用 curl 下载。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def share_id(share_path: str, fallback_url: str) -> str:
    data = json.loads(Path(share_path).read_text(encoding="utf-8"))
    url = data.get("url") or ""
    blob = " ".join([url, fallback_url, json.dumps(data, ensure_ascii=False)])
    patterns = [
        r"/(?:video|note|slides|photo)/(\d{8,})",
        r"modal_id=(\d{8,})",
        r"aweme_id=(\d{8,})",
        r"\b(\d{19})\b",
    ]
    for pat in patterns:
        m = re.search(pat, blob)
        if m:
            return m.group(1)
    return ""


def _download_urls(downloads) -> list[str]:
    urls: list[str] = []
    if isinstance(downloads, str):
        urls = [u.strip() for u in downloads.replace("\n", " ").split() if u.strip()]
    elif isinstance(downloads, list):
        for item in downloads:
            if isinstance(item, str) and item.strip():
                urls.append(item.strip())
            elif isinstance(item, dict):
                for k in ("url", "download_url", "play_url"):
                    if item.get(k):
                        urls.append(str(item[k]).strip())
                        break
    return urls


def download(detail_path: str, out: str, url: str, detail_id: str, ua: str) -> int:
    raw = json.loads(Path(detail_path).read_text(encoding="utf-8"))
    data = raw.get("data") or {}
    if not data:
        print("detail 没有 data 字段，消息: " + str(raw.get("message")), file=sys.stderr)
        return 4
    urls = _download_urls(data.get("downloads") or "")
    if not urls:
        print("data.downloads 为空，无法下载。message=" + str(raw.get("message")), file=sys.stderr)
        return 4

    title = data.get("desc") or data.get("title") or ""
    author = data.get("nickname") or data.get("mark") or ""
    out_p = Path(out)
    meta = {
        "platform": "douyin",
        "url": url,
        "detail_id": detail_id,
        "resolved_url": data.get("share_url") or f"https://www.douyin.com/video/{detail_id}",
        "title": title,
        "author": author,
        "unique_id": data.get("unique_id"),
        "desc": data.get("desc"),
        "duration": data.get("duration"),
        "type": data.get("type"),
        "downloads": urls,
        "message": raw.get("message"),
    }
    (out_p / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    referer = "https://www.douyin.com/"
    saved: list[str] = []
    for i, media_url in enumerate(urls, 1):
        dest = out_p / ("video.mp4" if len(urls) == 1 else f"media_{i:02d}.mp4")
        print(f"下载 {media_url[:80]}... -> {dest}", file=sys.stderr)
        cmd = [
            "curl", "-L", "--fail", "--retry", "2", "--max-redirs", "10",
            "--connect-timeout", "15", "--max-time", "300",
            "-A", ua,
            "-H", f"Referer: {referer}",
            "-o", str(dest),
            media_url,
        ]
        r = subprocess.run(cmd)
        if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            print(f"curl 下载失败: {dest}", file=sys.stderr)
            return 4
        saved.append(str(dest))

    meta["files"] = saved
    (out_p / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已保存 {len(saved)} 个文件", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("用法: douyin_parse.py share-id SHARE.json URL | download DETAIL.json OUT URL ID UA", file=sys.stderr)
        return 1
    cmd = argv[0]
    if cmd == "share-id":
        ident = share_id(argv[1], argv[2] if len(argv) > 2 else "")
        if ident:
            print(ident)
            return 0
        return 4
    if cmd == "download":
        return download(*argv[1:6])
    print(f"未知子命令: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
