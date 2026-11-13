#!/usr/bin/env bash
# 用 yt-dlp 下载 X / YouTube。按链接域名自动选参数，并写 info.json 与 meta.json。
# 用法: ytdlp.sh <链接> <输出目录>
#
# X：默认格式
# YouTube：--extractor-args youtube:player_client=android -f 18
set -uo pipefail

# 解析软链：放进 PATH 的软链也要找到真实的技能目录（老 macOS 的 readlink 没有 -f，用 python3 兜底）
CC_SELF="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}" 2>/dev/null \
  || printf '%s' "${BASH_SOURCE[0]}")"
SKILL_DIR="$(cd "$(dirname "$CC_SELF")/.." && pwd)"
# shellcheck source=lib.sh
if ! source "$SKILL_DIR/scripts/lib.sh"; then
  echo "ytdlp.sh: 加载 $SKILL_DIR/scripts/lib.sh 失败（文件缺失或出错）。请确认技能目录完整，软链要指向技能目录里的真实文件。" >&2
  exit 3
fi

usage() { echo "用法: $0 <X|YouTube 链接> <输出目录>" >&2; exit 1; }
[ $# -eq 2 ] || usage
URL="$1"
OUT="$2"
mkdir -p "$OUT"

if ! command -v yt-dlp >/dev/null 2>&1; then
  cc_err "找不到 yt-dlp（先运行 setup.sh）"
  exit 3
fi

PLATFORM="$(cc_detect_platform "$URL")"
case "$PLATFORM" in
  x|youtube) ;;
  *)
    cc_err "ytdlp.sh 只处理 X / YouTube，当前识别为: $PLATFORM"
    exit 2
    ;;
esac

LOG="$OUT/yt-dlp.log"
cc_info "yt-dlp 平台=$PLATFORM"

set +e
case "$PLATFORM" in
  x)
    yt-dlp \
      --write-info-json \
      --no-playlist \
      -o "$OUT/%(uploader_id)s-%(id)s.%(ext)s" \
      "$URL" >"$LOG" 2>&1
    ;;
  youtube)
    yt-dlp \
      --extractor-args "youtube:player_client=android" \
      -f 18 \
      --write-info-json \
      --no-playlist \
      -o "$OUT/%(id)s.%(ext)s" \
      "$URL" >"$LOG" 2>&1
    ;;
esac
st=$?
set -e

if [ "$st" -ne 0 ]; then
  cc_err "yt-dlp 失败（退出码 $st）。"
  tail -n 30 "$LOG" >&2 || true
  exit 4
fi

python3 - <<'PY' "$OUT" "$URL" "$PLATFORM"
import json, sys
from pathlib import Path

out, url, platform = sys.argv[1:4]
out_p = Path(out)
infos = sorted(out_p.glob("*.info.json"))
if not infos:
    # 有的版本会写成 %id%.info.json 或单独名字
    infos = list(out_p.rglob("*.info.json"))
info = {}
if infos:
    try:
        info = json.loads(infos[0].read_text(encoding="utf-8"))
    except Exception as e:
        print(f"读 info.json 失败: {e}", file=sys.stderr)

media_ext = {".mp4", ".m4a", ".mp3", ".webm", ".mkv", ".mov", ".wav", ".aac", ".opus"}
media = [p for p in out_p.iterdir() if p.is_file() and p.suffix.lower() in media_ext and p.stat().st_size > 0]
title = info.get("title") or info.get("fulltitle") or ""
author = info.get("uploader") or info.get("channel") or info.get("creator") or info.get("uploader_id") or ""
meta = {
    "platform": platform,
    "url": url,
    "title": title,
    "author": author,
    "id": info.get("id"),
    "duration": info.get("duration"),
    "files": [str(p) for p in media],
    "info_json": str(infos[0]) if infos else None,
}
(out_p / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
if not media:
    print("yt-dlp 成功退出但输出目录里没有媒体文件", file=sys.stderr)
    sys.exit(4)
print(f"yt-dlp 完成 title={title!r} author={author!r} files={len(media)}", file=sys.stderr)
PY
st=$?
if [ "$st" -ne 0 ]; then
  exit "$st"
fi
cc_ok "下载完成: $OUT"
exit 0
