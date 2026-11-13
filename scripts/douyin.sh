#!/usr/bin/env bash
# 用 TikTokDownloader Web API 下载一条抖音作品。
# 用法: douyin.sh <链接> <输出目录>
#
# 流程：必要时在工具目录后台启动 Web API -> POST /douyin/share 拿作品 ID
# -> POST /douyin/detail 取 data.downloads -> curl 下载，并写 meta.json。
# 绝不调用 POST /settings。
set -uo pipefail

# 解析软链：放进 PATH 的软链也要找到真实的技能目录（老 macOS 的 readlink 没有 -f，用 python3 兜底）
CC_SELF="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}" 2>/dev/null \
  || printf '%s' "${BASH_SOURCE[0]}")"
SKILL_DIR="$(cd "$(dirname "$CC_SELF")/.." && pwd)"
# shellcheck source=lib.sh
if ! source "$SKILL_DIR/scripts/lib.sh"; then
  echo "douyin.sh: 加载 $SKILL_DIR/scripts/lib.sh 失败（文件缺失或出错）。请确认技能目录完整，软链要指向技能目录里的真实文件。" >&2
  exit 3
fi

usage() { echo "用法: $0 <抖音链接> <输出目录>" >&2; exit 1; }
[ $# -eq 2 ] || usage
URL="$1"
OUT="$2"
mkdir -p "$OUT"

api_up() {
  curl -sf -o /dev/null --connect-timeout 2 --max-time 5 "${CC_DOUYIN_API}/docs"
}

ensure_api() {
  if api_up; then
    cc_info "抖音 Web API 已在运行: $CC_DOUYIN_API"
    return 0
  fi
  if [ ! -f "$CC_TIKTOK_DIR/main.py" ]; then
    cc_err "找不到 TikTokDownloader: $CC_TIKTOK_DIR  （先运行 setup.sh，或设置 CC_TOOLS_DIR / CC_TIKTOK_DIR）"
    return 10
  fi
  if ! command -v uv >/dev/null 2>&1; then
    cc_err "没有 uv，无法启动 TikTokDownloader"
    return 3
  fi
  cc_info "启动 TikTokDownloader Web API（目录 $CC_TIKTOK_DIR，日志 $CC_DOUYIN_API_LOG）"
  : > "$CC_DOUYIN_API_LOG"
  (
    cd "$CC_TIKTOK_DIR" || exit 1
    export CC_TIKTOK_DIR
    # 非交互启动：不走菜单。本机若 settings 里已是 run_command=7，直接 uv run python main.py 也可以。
    nohup uv run python "$SKILL_DIR/scripts/start_douyin_api.py" >>"$CC_DOUYIN_API_LOG" 2>&1 &
    echo $! > "$CC_DOUYIN_API_PID"
  )
  local i
  for i in $(seq 1 90); do
    if api_up; then
      cc_ok "Web API 已就绪（${i}s）"
      return 0
    fi
    sleep 1
  done
  cc_err "Web API 在 90 秒内没有就绪。日志末尾："
  tail -n 40 "$CC_DOUYIN_API_LOG" >&2 || true
  return 10
}

ensure_api
st=$?
if [ "$st" -ne 0 ]; then
  exit "$st"
fi

SHARE_JSON="$OUT/share_response.json"
DETAIL_JSON="$OUT/detail_response.json"

# 1) 解析短链 / 分享链接，拿到作品页和 ID
cc_info "POST /douyin/share"
if ! curl -sS --fail --connect-timeout 10 --max-time 90 \
    -H "Content-Type: application/json" \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$URL")" \
    "${CC_DOUYIN_API}/douyin/share" > "$SHARE_JSON"
then
  cc_err "POST /douyin/share 失败（接口无响应或非 2xx）"
  exit 4
fi

DETAIL_ID="$(python3 "$SKILL_DIR/scripts/douyin_parse.py" share-id "$SHARE_JSON" "$URL" || true)"
if [ -z "$DETAIL_ID" ]; then
  cc_err "share 响应里没有解析到作品 ID。见 $SHARE_JSON"
  python3 -c 'import sys; print(sys.stdin.read()[:800])' < "$SHARE_JSON" >&2 || true
  exit 4
fi
cc_info "作品 ID: $DETAIL_ID"

# 2) 作品详情
cc_info "POST /douyin/detail"
if ! curl -sS --fail --connect-timeout 10 --max-time 90 \
    -H "Content-Type: application/json" \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"detail_id": sys.argv[1]}))' "$DETAIL_ID")" \
    "${CC_DOUYIN_API}/douyin/detail" > "$DETAIL_JSON"
then
  cc_err "POST /douyin/detail 失败"
  exit 4
fi

# 3) 解析 downloads 并 curl 下载（带 UA 和 Referer），写 meta.json
python3 "$SKILL_DIR/scripts/douyin_parse.py" download "$DETAIL_JSON" "$OUT" "$URL" "$DETAIL_ID" "$CC_UA"
st=$?
if [ "$st" -ne 0 ]; then
  exit "$st"
fi
cc_ok "抖音下载完成: $OUT"
exit 0
