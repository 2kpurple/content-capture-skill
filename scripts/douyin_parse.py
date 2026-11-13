#!/usr/bin/env python3
"""解析 TikTokDownloader 的 share/detail 响应，并按 data.downloads 用 curl 下载。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

# TikTokDownloader 的作品类型：图集、实况（Live Photo）都是图片作品，不转录
IMAGE_TYPES = {"图集", "实况", "image", "images", "gallery", "livephoto", "live photo", "slides"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v", ".mkv", ".mp3", ".m4a"}


def sniff_ext(path: Path, url: str) -> str:
    """按文件头判断真实后缀；判断不了再看 URL 路径。返回空串表示不知道。"""
    try:
        with path.open("rb") as f:
            head = f.read(16)
    except OSError:
        head = b""
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:4] in (b"GIF8",):
        return ".gif"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1"):
            return ".heic"
        if brand in (b"avif", b"avis"):
            return ".avif"
        if brand in (b"M4A ",):
            return ".m4a"
        return ".mp4"
    if head[:4] == b"\x1aE\xdf\xa3":
        return ".webm"
    suf = Path(urlparse(url).path).suffix.lower()
    if suf in IMAGE_EXT or suf in VIDEO_EXT:
        return suf
    return ""


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
    work_type = str(data.get("type") or "").strip()
    kind = "images" if work_type.lower() in IMAGE_TYPES else "video"
    meta = {
        "platform": "douyin",
        "kind": kind,
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
    images: list[str] = []
    for i, media_url in enumerate(urls, 1):
        if kind == "images":
            stem = f"image_{i:02d}"
        else:
            stem = "video" if len(urls) == 1 else f"media_{i:02d}"
        tmp = out_p / (stem + ".part")
        print(f"下载 {media_url[:80]}... -> {out_p / stem}.*", file=sys.stderr)
        cmd = [
            "curl", "-L", "--fail", "--retry", "2", "--max-redirs", "10",
            "--connect-timeout", "15", "--max-time", "300",
            "-A", ua,
            "-H", f"Referer: {referer}",
            "-o", str(tmp),
            media_url,
        ]
        r = subprocess.run(cmd)
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            print(f"curl 下载失败: {tmp}", file=sys.stderr)
            return 4
        # 后缀按文件头判断，不再一律写成 .mp4
        ext = sniff_ext(tmp, media_url) or (".jpg" if kind == "images" else ".mp4")
        dest = tmp.with_suffix(ext)
        tmp.replace(dest)
        if ext in IMAGE_EXT:
            images.append(str(dest))
        else:
            saved.append(str(dest))

    if kind == "video" and not saved and images:
        # 类型字段没标图集，但下回来的全是图片：按图片作品处理
        kind = "images"
        meta["kind"] = kind
    # files 只放可转录的音视频；图片单独放 images
    meta["files"] = saved if kind == "video" else []
    meta["images"] = images
    if kind == "images":
        meta["live_clips"] = saved  # 实况图里的短视频片段（不转录）
    (out_p / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已保存 {len(saved)} 个音视频、{len(images)} 张图片（类型 {work_type or '未知'}）", file=sys.stderr)
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
