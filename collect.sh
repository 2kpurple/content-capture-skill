#!/usr/bin/env bash
# 内容收录总入口：按链接域名分派下载，视频平台下完自动转录，公众号走 wxfetch。
#
#   collect.sh [--max-seconds N] [--skip-transcribe] <链接> [输出目录]
#
# 最后向 stdout 打印一段 JSON 摘要（平台、标题、作者、文件路径、状态）。
# 失败给明确的退出码和原因，不假装成功。
#
# 退出码：
#   0  成功
#   1  用法错误
#   2  不支持或无法识别的链接
#   3  依赖缺失
#   4  下载失败
#   5  转录失败
#   6  公众号抓取失败（JSON 里会带上 wxfetch 的退出码）
#  10  工具未就绪（如下载器或抖音 API）
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SKILL_DIR/scripts/lib.sh"

MAX_SECONDS="${CC_MAX_SECONDS:-}"
SKIP_TRANSCRIBE=0
URL=""
OUT=""

usage() {
  sed -n '2,18p' "$0" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage ;;
    --skip-transcribe) SKIP_TRANSCRIBE=1; shift ;;
    --max-seconds)
      [ $# -ge 2 ] || usage
      MAX_SECONDS="$2"
      shift 2
      ;;
    --max-seconds=*)
      MAX_SECONDS="${1#--max-seconds=}"
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      cc_err "未知参数: $1"
      usage
      ;;
    *)
      if [ -z "$URL" ]; then
        URL="$1"
      elif [ -z "$OUT" ]; then
        OUT="$1"
      else
        cc_err "多余参数: $1"
        usage
      fi
      shift
      ;;
  esac
done

[ -n "$URL" ] || usage
if [ -z "$OUT" ]; then
  OUT="$(pwd)/content-capture-out/$(date +%Y%m%d-%H%M%S)-$(cc_slug "$URL")"
fi
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

PLATFORM="$(cc_detect_platform "$URL")"
SUMMARY="$OUT/summary.json"

write_summary() {
  # write_summary ok code message  —— 其余字段从 meta.json / 文件扫描补齐
  python3 - "$SUMMARY" "$OUT" "$URL" "$PLATFORM" "$1" "$2" "$3" <<'PY'
import json, sys
from pathlib import Path

summary_path, out, url, platform, ok, code, message = sys.argv[1:8]
out_p = Path(out)
meta = {}
mp = out_p / "meta.json"
if mp.exists():
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        meta = {}

# 公众号 article.json
if not meta:
    arts = list(out_p.rglob("article.json"))
    if arts:
        try:
            art = json.loads(arts[0].read_text(encoding="utf-8"))
            meta = {
                "title": art.get("title") or "",
                "author": art.get("author") or art.get("account_name") or "",
                "account_name": art.get("account_name"),
                "article_id": art.get("article_id"),
                "files": art.get("files") or {},
            }
        except Exception:
            pass

files = {
    "meta": str(mp) if mp.exists() else None,
    "transcript": None,
    "transcript_plain": None,
    "media": [],
    "markdown": [],
    "other": [],
}
media_ext = {".mp4", ".m4a", ".mp3", ".webm", ".mkv", ".mov", ".wav", ".aac", ".opus"}
skip_names = {"summary.json", "yt-dlp.log", "xhs_cli.log", "share_response.json", "detail_response.json"}
for p in sorted(out_p.rglob("*")):
    if not p.is_file():
        continue
    rel = str(p)
    name = p.name
    if name in skip_names:
        continue
    suf = p.suffix.lower()
    if name == "transcript.txt":
        files["transcript"] = rel
    elif name == "transcript_plain.txt":
        files["transcript_plain"] = rel
    elif name.endswith(".md") or name == "article.md":
        files["markdown"].append(rel)
    elif suf in media_ext:
        files["media"].append(rel)
    elif name in {"meta.json", "article.json"} or suf == ".json":
        pass
    else:
        if name not in {"audio.wav", "audio_16k_mono.wav"}:
            files["other"].append(rel)

title = meta.get("title") or ""
author = meta.get("author") or meta.get("account_name") or ""
payload = {
    "ok": ok == "ok",
    "status": "ok" if ok == "ok" else "error",
    "error_code": int(code),
    "message": message,
    "platform": platform,
    "url": url,
    "title": title,
    "author": author,
    "out_dir": out,
    "files": files,
}
Path(summary_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

fail() {
  local code="$1" msg="$2"
  cc_err "$msg"
  write_summary error "$code" "$msg"
  exit "$code"
}

cc_info "平台=$PLATFORM  输出=$OUT"

case "$PLATFORM" in
  unknown)
    fail 2 "无法识别的链接（支持抖音、小红书、X、YouTube、微信公众号）"
    ;;
  douyin)
    bash "$SKILL_DIR/scripts/douyin.sh" "$URL" "$OUT"
    st=$?
    [ "$st" -eq 0 ] || fail "$st" "抖音下载失败（退出码 $st）"
    ;;
  xhs)
    bash "$SKILL_DIR/scripts/xhs.sh" "$URL" "$OUT"
    st=$?
    [ "$st" -eq 0 ] || fail "$st" "小红书下载失败（退出码 $st）"
    ;;
  x|youtube)
    bash "$SKILL_DIR/scripts/ytdlp.sh" "$URL" "$OUT"
    st=$?
    [ "$st" -eq 0 ] || fail "$st" "$PLATFORM 下载失败（退出码 $st）"
    ;;
  wechat)
    if [ ! -x "$SKILL_DIR/wxfetch/wxfetch" ]; then
      fail 3 "找不到 wxfetch 脚本"
    fi
    set +e
    "$SKILL_DIR/wxfetch/wxfetch" "$URL" --out "$OUT" --format both --download-images -q >"$OUT/wxfetch_stdout.json"
    st=$?
    set -e
    if [ "$st" -ne 0 ]; then
      fail 6 "公众号抓取失败（wxfetch 退出码 $st）"
    fi
    write_summary ok 0 "公众号抓取成功"
    exit 0
    ;;
esac

# 视频/音频平台：自动转录
if [ "$SKIP_TRANSCRIBE" = 1 ]; then
  write_summary ok 0 "下载成功（已跳过转录）"
  exit 0
fi

MEDIA="$(python3 - <<'PY' "$OUT"
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
media = []
exts = {".mp4", ".m4a", ".mp3", ".webm", ".mkv", ".mov", ".wav", ".aac", ".opus"}
meta = out / "meta.json"
if meta.exists():
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        for f in data.get("files") or []:
            p = Path(f)
            if p.is_file() and p.suffix.lower() in exts:
                media.append(str(p))
    except Exception:
        pass
if not media:
    media = [str(p) for p in out.rglob("*") if p.is_file() and p.suffix.lower() in exts and p.stat().st_size > 0]
print(media[0] if media else "")
PY
)"

if [ -z "$MEDIA" ]; then
  fail 4 "下载看起来成功，但没有找到可转录的媒体文件"
fi

PY="${CC_VENV}/bin/python"
if [ ! -x "$PY" ]; then
  fail 3 "找不到转录环境: $CC_VENV （先运行 setup.sh，或设置 CC_VENV）"
fi

TRANS_ARGS=("$PY" "$SKILL_DIR/scripts/transcribe.py" --out-dir "$OUT" "$MEDIA")
if [ -n "$MAX_SECONDS" ]; then
  TRANS_ARGS+=(--max-seconds "$MAX_SECONDS")
  cc_info "转录 $MEDIA （仅前 ${MAX_SECONDS} 秒）"
else
  cc_info "转录 $MEDIA"
fi
set +e
"${TRANS_ARGS[@]}"
st=$?
set -e
if [ "$st" -ne 0 ]; then
  fail 5 "转录失败（退出码 $st）"
fi

write_summary ok 0 "下载并转录成功"
exit 0
