#!/usr/bin/env bash
# 内容收录技能的共用变量与小函数。被 setup.sh / collect.sh / 各平台脚本 source。
# 本文件只定义函数和默认路径，不在被 source 时直接退出。

# 已加载则跳过，避免重复 source
if [ "${CC_LIB_LOADED:-}" = "1" ]; then
  return 0 2>/dev/null || true
fi
CC_LIB_LOADED=1

# 调用方应先设好 SKILL_DIR。若没有，就按「本文件在 scripts/」反推。
if [ -z "${SKILL_DIR:-}" ]; then
  SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

# 常用可执行文件可能装在用户目录
export PATH="${HOME}/.local/bin:${PATH}"

# ---------- 可覆盖的环境变量 ----------
# 工具目录：下面放 TikTokDownloader、XHS-Downloader
# 本机若已有，请设为现成目录，不要再 clone。
: "${CC_TOOLS_DIR:=${HOME}/.local/share/content-capture/tools}"
# 单个工具目录可再单独覆盖
: "${CC_TIKTOK_DIR:=${CC_TOOLS_DIR}/TikTokDownloader}"
: "${CC_XHS_DIR:=${CC_TOOLS_DIR}/XHS-Downloader}"
# 转录虚拟环境（faster-whisper + PyAV 13）
: "${CC_VENV:=${HOME}/.local/share/content-capture/venv}"
# Whisper 模型：模型名（默认 small）或本地目录路径
: "${CC_WHISPER_MODEL:=small}"
# 抖音 Web API
: "${CC_DOUYIN_API:=http://127.0.0.1:5555}"
: "${CC_DOUYIN_API_LOG:=/tmp/content-capture-douyin-api.log}"
: "${CC_DOUYIN_API_PID:=/tmp/content-capture-douyin-api.pid}"

CC_UA="${CC_UA:-Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36}"

cc_ok()  { printf '  [ OK ] %s\n' "$*" >&2; }
cc_bad() { printf '  [MISS] %s\n' "$*" >&2; }
cc_info(){ printf '  [....] %s\n' "$*" >&2; }
cc_err() { printf '  [ERR ] %s\n' "$*" >&2; }

# 判断路径是否像本地模型目录
cc_is_model_path() {
  local p="$1"
  [ -d "$p" ] || return 1
  [ -f "$p/model.bin" ] || [ -f "$p/config.json" ]
}

# 把任意字符串收成适合做目录名的一段
cc_slug() {
  python3 -c 'import re,sys; s=re.sub(r"[^\w\u4e00-\u9fff.-]+","_",sys.argv[1]).strip("._") or "item"; print(s[:80])' "$1"
}

# 识别链接所属平台，输出：douyin|xhs|x|youtube|wechat|unknown
cc_detect_platform() {
  local url="$1"
  local host
  host="$(python3 -c 'import sys; from urllib.parse import urlparse; u=sys.argv[1].strip();
p=urlparse(u if "://" in u else "https://"+u); print((p.netloc or "").lower())' "$url")"
  host="${host#www.}"
  case "$host" in
    douyin.com|v.douyin.com|iesdouyin.com|*.douyin.com|*.iesdouyin.com) echo douyin ;;
    xiaohongshu.com|xhslink.com|*.xiaohongshu.com|*.xhslink.com) echo xhs ;;
    x.com|twitter.com|t.co|mobile.twitter.com|*.x.com|*.twitter.com) echo x ;;
    youtube.com|youtu.be|m.youtube.com|youtube-nocookie.com|*.youtube.com|*.youtu.be) echo youtube ;;
    mp.weixin.qq.com|weixin.qq.com|*.weixin.qq.com) echo wechat ;;
    *) echo unknown ;;
  esac
}

cc_json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$1"
}
