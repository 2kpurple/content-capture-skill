#!/usr/bin/env bash
# 用 XHS-Downloader 下载一条小红书笔记。
# 用法: xhs.sh <链接> <输出目录>
#
# 命令：uv run main.py -l zh_CN -u 链接 --work_path 输出目录 --note_format all --folder_mode true
# 若视频没下下来，把输出里的 http:// xhscdn 地址改成 https://，再用 curl 补下。
set -uo pipefail

# 解析软链：放进 PATH 的软链也要找到真实的技能目录（老 macOS 的 readlink 没有 -f，用 python3 兜底）
CC_SELF="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}" 2>/dev/null \
  || printf '%s' "${BASH_SOURCE[0]}")"
SKILL_DIR="$(cd "$(dirname "$CC_SELF")/.." && pwd)"
# shellcheck source=lib.sh
if ! source "$SKILL_DIR/scripts/lib.sh"; then
  echo "xhs.sh: 加载 $SKILL_DIR/scripts/lib.sh 失败（文件缺失或出错）。请确认技能目录完整，软链要指向技能目录里的真实文件。" >&2
  exit 3
fi

usage() { echo "用法: $0 <小红书链接> <输出目录>" >&2; exit 1; }
[ $# -eq 2 ] || usage
URL="$1"
OUT="$2"
mkdir -p "$OUT"

if [ ! -f "$CC_XHS_DIR/main.py" ]; then
  cc_err "找不到 XHS-Downloader: $CC_XHS_DIR  （先运行 setup.sh，或设置 CC_TOOLS_DIR / CC_XHS_DIR）"
  exit 10
fi
if ! command -v uv >/dev/null 2>&1; then
  cc_err "没有 uv，无法运行 XHS-Downloader"
  exit 3
fi

LOG="$OUT/xhs_cli.log"
cc_info "运行 XHS-Downloader"
# 不改工具自带的配置文件。--record_data true 是为了留下下载地址，失败时才能 https 补下。
set +e
(
  cd "$CC_XHS_DIR" || exit 1
  uv run main.py -l zh_CN -u "$URL" --work_path "$OUT" --note_format all --folder_mode true --record_data true
) >"$LOG" 2>&1
cli_st=$?
set -e
if [ "$cli_st" -ne 0 ]; then
  cc_info "XHS-Downloader 退出码 $cli_st，继续检查是否已写出文案/地址（见 $LOG）"
fi

python3 "$SKILL_DIR/scripts/xhs_finish.py" "$OUT" "$URL" "$CC_UA" "$CC_XHS_DIR"
st=$?
exit "$st"
