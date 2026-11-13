#!/usr/bin/env bash
# 内容收录技能：幂等安装 / 自检
#
#   bash setup.sh            # 检查并补齐依赖
#   bash setup.sh --check    # 只检查，缺东西时退出码 1
#   bash setup.sh --help
#
# 环境变量见 README.md 与 scripts/lib.sh（CC_TOOLS_DIR、CC_VENV、CC_WHISPER_MODEL 等）。
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SKILL_DIR/scripts/lib.sh"

MODE="install"
case "${1:-}" in
  "" ) MODE="install" ;;
  --check) MODE="check" ;;
  -h|--help)
    sed -n '2,12p' "$0"
    exit 0
    ;;
  *)
    echo "未知参数: $1  （用 --help 查看用法）" >&2
    exit 2
    ;;
esac

MISSING=0
echo "== 内容收录 setup (mode=$MODE) ==" >&2
echo "   skill=$SKILL_DIR" >&2
echo "   tools=$CC_TOOLS_DIR" >&2
echo "   tiktok=$CC_TIKTOK_DIR" >&2
echo "   xhs=$CC_XHS_DIR" >&2
echo "   venv=$CC_VENV" >&2
echo "   whisper=$CC_WHISPER_MODEL" >&2

have() { command -v "$1" >/dev/null 2>&1; }

# 非交互装系统包（能装就装，没权限就报出来）
cc_apt_install() {
  if ! have apt-get; then
    cc_err "没有 apt-get，请手动安装: $*"
    return 1
  fi
  local sudo=""
  if [ "$(id -u)" -ne 0 ]; then
    if have sudo && sudo -n true 2>/dev/null; then sudo="sudo -n"; else
      cc_err "需要 root/sudo 才能安装: $*"
      return 1
    fi
  fi
  # shellcheck disable=SC2086
  DEBIAN_FRONTEND=noninteractive $sudo apt-get update -qq >/dev/null 2>&1 || true
  # shellcheck disable=SC2086
  DEBIAN_FRONTEND=noninteractive $sudo apt-get install -y -qq "$@" >/dev/null
}

# ---------- 1. yt-dlp / ffmpeg / uv ----------
if have yt-dlp; then
  cc_ok "yt-dlp: $(yt-dlp --version 2>/dev/null | head -1)"
else
  cc_bad "yt-dlp"
  if [ "$MODE" = check ]; then
    MISSING=1
  else
    if have uv; then
      cc_info "用 uv 安装 yt-dlp"
      uv tool install yt-dlp && cc_ok "yt-dlp installed" || { cc_err "yt-dlp 安装失败"; MISSING=1; }
    else
      cc_err "没有 uv，无法自动安装 yt-dlp"
      MISSING=1
    fi
  fi
fi

if have ffmpeg; then
  cc_ok "ffmpeg: $(ffmpeg -version 2>/dev/null | head -1)"
else
  cc_bad "ffmpeg"
  if [ "$MODE" = check ]; then
    MISSING=1
  else
    cc_apt_install ffmpeg && cc_ok "ffmpeg installed" || { cc_err "ffmpeg 安装失败"; MISSING=1; }
  fi
fi

if have uv; then
  cc_ok "uv: $(uv --version 2>/dev/null)"
else
  cc_bad "uv"
  if [ "$MODE" = check ]; then
    MISSING=1
  else
    cc_info "安装 uv"
    if curl -fsSL https://astral.sh/uv/install.sh | sh; then
      export PATH="${HOME}/.local/bin:${PATH}"
      have uv && cc_ok "uv installed" || { cc_err "uv 安装后仍不在 PATH"; MISSING=1; }
    else
      cc_err "uv 安装失败"
      MISSING=1
    fi
  fi
fi

# ---------- 2. 转录虚拟环境 ----------
venv_ok() {
  local py="${CC_VENV}/bin/python"
  [ -x "$py" ] || return 1
  "$py" - <<'PY' >/dev/null 2>&1
import faster_whisper, av
# 粗查版本，不对也算不通过
import importlib.metadata as m
fw = m.version("faster-whisper")
avv = m.version("av")
assert fw.startswith("1.2."), fw
# PyAV 19 与 faster-whisper 1.2 不兼容，要求 13.x
assert avv.startswith("13."), avv
PY
}

if venv_ok; then
  cc_ok "转录环境: $CC_VENV (faster-whisper 1.2.x + av 13.x)"
else
  cc_bad "转录环境未就绪: $CC_VENV"
  if [ "$MODE" = check ]; then
    MISSING=1
  else
    if ! have uv; then
      cc_err "没有 uv，无法创建转录环境"
      MISSING=1
    else
      cc_info "创建/修复转录环境并安装 faster-whisper==1.2.1 av==13.1.0"
      mkdir -p "$(dirname "$CC_VENV")"
      if [ ! -x "${CC_VENV}/bin/python" ]; then
        uv venv "$CC_VENV" || { cc_err "uv venv 失败"; MISSING=1; }
      fi
      if [ -x "${CC_VENV}/bin/python" ]; then
        uv pip install --python "${CC_VENV}/bin/python" "faster-whisper==1.2.1" "av==13.1.0" \
          && venv_ok && cc_ok "转录环境已就绪" \
          || { cc_err "转录依赖安装失败（需要 faster-whisper==1.2.1 和 av==13.1.0）"; MISSING=1; }
      fi
    fi
  fi
fi

# ---------- 3. Whisper 模型路径（只检查，不在这里下载大模型） ----------
if cc_is_model_path "$CC_WHISPER_MODEL"; then
  cc_ok "Whisper 模型目录: $CC_WHISPER_MODEL"
else
  case "$CC_WHISPER_MODEL" in
    small|tiny|base|medium|large-v2|large-v3)
      cc_ok "Whisper 模型名: $CC_WHISPER_MODEL（首次转录时由 faster-whisper 按需下载）"
      ;;
    *)
      if [ -e "$CC_WHISPER_MODEL" ]; then
        cc_bad "CC_WHISPER_MODEL 路径存在但看起来不是模型目录: $CC_WHISPER_MODEL"
        MISSING=1
      else
        # 允许模型名；未知名字也提示，但不强制失败（faster-whisper 还可能认识）
        cc_info "CC_WHISPER_MODEL=$CC_WHISPER_MODEL （将按模型名交给 faster-whisper）"
      fi
      ;;
  esac
fi

# ---------- 4. TikTokDownloader / XHS-Downloader ----------
# 已有目录就复用，绝不把整仓复制进技能文件夹，也不在已存在时重复 clone。
ensure_git_tool() {
  local name="$1" url="$2" dest="$3"
  if [ -f "$dest/main.py" ]; then
    cc_ok "$name: $dest"
    if [ "$MODE" != check ] && have uv && [ -f "$dest/pyproject.toml" ] && [ ! -d "$dest/.venv" ]; then
      cc_info "在 $dest 执行 uv sync"
      (cd "$dest" && uv sync) || cc_info "uv sync 失败（若环境已能跑可忽略）"
    fi
    return 0
  fi
  cc_bad "$name 不在 $dest"
  if [ "$MODE" = check ]; then
    MISSING=1
    return 1
  fi
  if ! have git; then
    cc_err "没有 git，无法 clone $name"
    MISSING=1
    return 1
  fi
  if ! have uv; then
    cc_err "没有 uv，clone 后也无法 uv sync $name"
    MISSING=1
    return 1
  fi
  mkdir -p "$(dirname "$dest")"
  cc_info "git clone --depth 1 $url -> $dest"
  if git clone --depth 1 "$url" "$dest"; then
    (cd "$dest" && uv sync) && cc_ok "$name 已安装" || { cc_err "$name uv sync 失败"; MISSING=1; return 1; }
  else
    cc_err "$name clone 失败"
    MISSING=1
    return 1
  fi
}

ensure_git_tool "TikTokDownloader" "https://github.com/JoeanAmier/TikTokDownloader.git" "$CC_TIKTOK_DIR"
ensure_git_tool "XHS-Downloader" "https://github.com/JoeanAmier/XHS-Downloader.git" "$CC_XHS_DIR"

# ---------- 5. 公众号 wxfetch ----------
if [ -x "$SKILL_DIR/wxfetch/setup.sh" ]; then
  cc_info "调用 wxfetch/setup.sh${MODE:+ }$( [ "$MODE" = check ] && echo --check )"
  if [ "$MODE" = check ]; then
    bash "$SKILL_DIR/wxfetch/setup.sh" --check || MISSING=1
  else
    bash "$SKILL_DIR/wxfetch/setup.sh" || MISSING=1
  fi
else
  cc_bad "找不到 $SKILL_DIR/wxfetch/setup.sh"
  MISSING=1
fi

if [ "$MISSING" = 0 ]; then
  echo "== READY ==" >&2
  exit 0
fi
echo "== NOT READY（见上方 [MISS]/[ERR]；安装请运行: bash $SKILL_DIR/setup.sh）==" >&2
exit 1
