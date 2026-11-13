#!/usr/bin/env python3
"""整理 XHS-Downloader 的输出；视频没下成时，把 http://xhscdn 改成 https:// 用 curl 补下。

图文、图集笔记只保存图片和文案：不把图片当 .mp4 补下，也不交给转录（meta.kind = images）。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

MEDIA_EXT = {".mp4", ".mov", ".webm", ".m4v", ".mp3", ".m4a", ".wav"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".avif"}
NOTE_EXT = {".md", ".txt", ".json"}
# XHS-Downloader 的作品类型：图文、图集按图片下载；只有「视频」需要转录
IMAGE_TYPES = {"图文", "图集", "image", "images", "normal", "gallery"}
VIDEO_TYPES = {"视频", "video"}


def sniff_kind(path: Path) -> str:
    """按文件头判断下回来的是图片还是音视频：image / av / 空串。"""
    try:
        with path.open("rb") as f:
            head = f.read(16)
    except OSError:
        return ""
    if head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG") or head[:4] == b"GIF8":
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    if head[4:8] == b"ftyp":
        return "image" if head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"avif", b"avis") else "av"
    if head[:4] == b"\x1aE\xdf\xa3" or head[:3] == b"ID3" or head[:4] == b"RIFF":
        return "av"
    return ""


def image_suffix(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(16)
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head[:4] == b"RIFF":
        return ".webp"
    if head[:4] == b"GIF8":
        return ".gif"
    if head[4:8] == b"ftyp":
        return ".avif" if head[8:12] in (b"avif", b"avis") else ".heic"
    return ".jpg"


def iter_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.name not in {"ExploreData.db", "xhs_cli.log", "meta.json"}:
            yield p


def add_url(cdn_urls: list[str], u: str) -> None:
    u = (u or "").strip().strip("\"'")
    if not u:
        return
    if u.startswith("http://") and "xhscdn" in u:
        u = "https://" + u[len("http://") :]
    if u.startswith("http") and u not in cdn_urls:
        cdn_urls.append(u)


def parse_maybe_list(val) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x]
    s = str(val)
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
        if parsed:
            return [str(parsed)]
    except Exception:
        pass
    return [part for part in re.split(r"[\s,]+", s) if part]


def collect_from_db(out_p: Path, cdn_urls: list[str]) -> tuple[str, str, str]:
    title, author, work_type = "", "", ""
    for db in out_p.rglob("ExploreData.db"):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cols = [r[1] for r in con.execute("PRAGMA table_info(explore_data)")]
            if "下载地址" in cols:
                for (val,) in con.execute("SELECT 下载地址 FROM explore_data"):
                    for item in parse_maybe_list(val):
                        add_url(cdn_urls, item)
            if "作品标题" in cols:
                row = con.execute("SELECT 作品标题, 作者昵称 FROM explore_data LIMIT 1").fetchone()
                if row:
                    title = title or (row[0] or "")
                    author = author or (row[1] or "")
            if "作品类型" in cols:
                row = con.execute("SELECT 作品类型 FROM explore_data LIMIT 1").fetchone()
                if row:
                    work_type = work_type or (row[0] or "")
            con.close()
        except Exception as e:
            print(f"读 {db} 失败: {e}", file=sys.stderr)
    return title, author, work_type


def extract_urls(xhs_dir: str, out_p: Path, url: str) -> dict | None:
    """CLI 没留下地址时，再 extract 一次（只取元数据和下载地址，不让它下）。"""
    dest = out_p / "extract_meta.json"
    env = os.environ.copy()
    env["CC_XHS_DIR"] = xhs_dir
    env["CC_OUT"] = str(out_p)
    env["CC_URL"] = url
    env["CC_EXTRACT_JSON"] = str(dest)
    # 单独脚本，避免在这里嵌套大段代码。
    helper = Path(__file__).with_name("xhs_extract.py")
    r = subprocess.run(
        ["uv", "run", "python", str(helper)],
        cwd=xhs_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[-1500:]
        print("extract 失败:", err, file=sys.stderr)
        return None
    try:
        return json.loads(dest.read_text(encoding="utf-8"))
    except Exception:
        return None


def curl_one(media_url: str, dest: Path, ua: str) -> bool:
    print(f"https 补下 {media_url} -> {dest}", file=sys.stderr)
    cmd = [
        "curl", "-L", "--fail", "--retry", "2", "--max-redirs", "10",
        "--connect-timeout", "15", "--max-time", "300",
        "-A", ua,
        "-o", str(dest),
        media_url,
    ]
    r = subprocess.run(cmd)
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def main() -> int:
    if len(sys.argv) != 5:
        print("用法: xhs_finish.py OUT URL UA XHS_DIR", file=sys.stderr)
        return 1
    out, url, ua, xhs_dir = sys.argv[1:5]
    out_p = Path(out)

    media = [p for p in iter_files(out_p) if p.suffix.lower() in MEDIA_EXT and p.stat().st_size > 0]
    notes = [p for p in iter_files(out_p) if p.suffix.lower() in NOTE_EXT]

    title = author = ""
    text_blob = ""
    for p in notes:
        try:
            text_blob += "\n" + p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    m = re.search(r"作品标题[：:]\s*`?(.+?)`?\s*$", text_blob, re.M)
    if m:
        title = m.group(1).strip()
    m = re.search(r"作者昵称[：:]\s*`?(.+?)`?\s*$", text_blob, re.M)
    if m:
        author = m.group(1).strip()

    work_type = ""
    m = re.search(r"作品类型[：:]\s*`?(.+?)`?\s*$", text_blob, re.M)
    if m:
        work_type = m.group(1).strip()

    cdn_urls: list[str] = []
    db_title, db_author, db_type = collect_from_db(out_p, cdn_urls)
    title = title or db_title
    author = author or db_author
    work_type = work_type or db_type
    for found in re.findall(r"https?://[^\s\"'<>]+xhscdn[^\s\"'<>]+", text_blob):
        add_url(cdn_urls, found)

    if not media and not cdn_urls:
        print("CLI 未留下媒体或下载地址，改用 extract(download=False) 取地址", file=sys.stderr)
        data = extract_urls(xhs_dir, out_p, url)
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            title = title or item.get("作品标题") or ""
            author = author or item.get("作者昵称") or ""
            work_type = work_type or str(item.get("作品类型") or "")
            for u in parse_maybe_list(item.get("下载地址") or []):
                add_url(cdn_urls, u)

    images = [p for p in iter_files(out_p) if p.suffix.lower() in IMAGE_EXT and p.stat().st_size > 0]
    wt = work_type.strip().lower()
    if wt in IMAGE_TYPES:
        kind = "images"
    elif wt in VIDEO_TYPES:
        kind = "video"
    else:
        # 类型未知：没有音视频、只有图片时按图文处理
        kind = "images" if (images and not media) else "video"

    saved_new: list[Path] = []
    if kind == "images" and not images and cdn_urls:
        # 图文笔记但图片没下成：按图片补下，后缀按文件头定，不写成 .mp4
        dest_dir = notes[0].parent if notes else (out_p / "Download" / "manual")
        dest_dir.mkdir(parents=True, exist_ok=True)
        for i, img_url in enumerate(cdn_urls, 1):
            tmp = dest_dir / f"image_{i:02d}.part"
            if curl_one(img_url, tmp, ua) and sniff_kind(tmp) == "image":
                dest = tmp.with_suffix(image_suffix(tmp))
                tmp.replace(dest)
                images.append(dest)
            else:
                tmp.unlink(missing_ok=True)
                print(f"图片补下失败或不是图片: {img_url}", file=sys.stderr)
    if kind == "video" and not media and cdn_urls:
        dest_dir = notes[0].parent if notes else (out_p / "Download" / "manual")
        dest_dir.mkdir(parents=True, exist_ok=True)
        for i, media_url in enumerate(cdn_urls, 1):
            lower = media_url.lower()
            suffix = ".m4a" if (".m4a" in lower or ".mp3" in lower) else ".mp4"
            dest = dest_dir / ("video" + suffix if len(cdn_urls) == 1 else f"media_{i:02d}{suffix}")
            if curl_one(media_url, dest, ua):
                if sniff_kind(dest) == "image":
                    # 地址其实是图片（例如封面），改回图片后缀，不拿去转录
                    img = dest.with_suffix(image_suffix(dest))
                    dest.replace(img)
                    images.append(img)
                    continue
                saved_new.append(dest)
            else:
                print(f"补下失败: {media_url}", file=sys.stderr)
        media = saved_new

    if not media:
        media = [p for p in iter_files(out_p) if p.suffix.lower() in MEDIA_EXT and p.stat().st_size > 0]

    if kind == "video" and not media and images:
        kind = "images"

    meta = {
        "platform": "xhs",
        "kind": kind,
        "work_type": work_type,
        "url": url,
        "title": title,
        "author": author,
        # files 只放可转录的音视频；图文笔记为空，图片在 images
        "files": [str(p) for p in media] if kind == "video" else [],
        "images": [str(p) for p in images],
        "notes": [str(p) for p in notes],
        "cdn_urls": cdn_urls,
        "https_fallback_downloaded": [str(p) for p in saved_new],
    }
    (out_p / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if kind == "images":
        if not images and not notes:
            print("小红书图文：既没有文案也没有图片，下载失败。", file=sys.stderr)
            return 4
        print(f"小红书图文完成 title={title!r} author={author!r} images={len(images)}（不转录）", file=sys.stderr)
        return 0
    if not media and not notes:
        print("小红书既没有文案也没有媒体，下载失败。", file=sys.stderr)
        return 4
    if not media:
        print("已拿到笔记文案，但视频下载失败（没有可用媒体文件）。", file=sys.stderr)
        return 4
    print(f"小红书完成 title={title!r} author={author!r} media={len(media)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
