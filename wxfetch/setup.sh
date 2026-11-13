#!/usr/bin/env bash
# wechat-article-fetch: 环境自检 + 自动安装（幂等，可反复执行）
#
#   bash setup.sh            # 检查并安装全部依赖（核心 + Chromium 浏览器降级）
#   bash setup.sh --core     # 只装核心（纯 HTTP 主路径），不装浏览器
#   bash setup.sh --browser  # 确保核心 + 浏览器（同默认）
#   bash setup.sh --check    # 只检查不安装（doctor 模式），缺失时退出码 1
#
# 环境变量：
#   WXFETCH_VENV               虚拟环境路径（默认 ~/.local/share/wxfetch/venv）
#   PLAYWRIGHT_BROWSERS_PATH   Playwright 浏览器缓存目录（默认 ~/.cache/ms-playwright）
#   PIP_INDEX_URL              可选 pip 镜像
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${WXFETCH_VENV:-$HOME/.local/share/wxfetch/venv}"
PY="$VENV/bin/python"
REQ="$DIR/requirements.txt"
MODE="all"
case "${1:-}" in
  --core) MODE="core" ;;
  --browser|"") MODE="all" ;;
  --check) MODE="check" ;;
  -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

ok()   { printf '  [ OK ] %s\n' "$*" >&2; }
bad()  { printf '  [MISS] %s\n' "$*" >&2; }
info() { printf '  [....] %s\n' "$*" >&2; }
MISSING=0

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then SUDO="sudo -n"; fi
fi
apt_install() {
  if ! command -v apt-get >/dev/null 2>&1; then echo "apt-get not found; please install manually: $*" >&2; return 1; fi
  if [ "$(id -u)" -ne 0 ] && [ -z "$SUDO" ]; then echo "need root/sudo to apt-get install: $*" >&2; return 1; fi
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get update -qq >/dev/null 2>&1 || true
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq "$@" >/dev/null
}

echo "== wechat-article-fetch setup (mode=$MODE) ==" >&2
echo "   dir=$DIR  venv=$VENV" >&2

# 1. python3
if command -v python3 >/dev/null 2>&1; then
  ok "python3: $(python3 --version 2>&1)"
else
  bad "python3"
  if [ "$MODE" = check ]; then MISSING=1; else apt_install python3 python3-venv python3-pip && ok "python3 installed" || { echo "FATAL: cannot install python3" >&2; exit 1; }; fi
fi

# 2. venv module (Debian/Ubuntu 需要 python3-venv / python3.X-venv)
venv_works() { local t; t="$(mktemp -d)"; python3 -m venv "$t/v" >/dev/null 2>&1; local r=$?; rm -rf "$t"; return $r; }
if [ -x "$PY" ] && "$PY" -c 'import sys' >/dev/null 2>&1; then
  ok "venv: $VENV"
else
  if [ "$MODE" = check ]; then bad "venv not created: $VENV"; MISSING=1
  else
    if ! venv_works; then
      info "python venv module missing, installing python3-venv"
      PYV="$(python3 -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
      apt_install python3-venv "python${PYV}-venv" || apt_install python3-venv || true
    fi
    rm -rf "$VENV"
    if python3 -m venv "$VENV" >/dev/null 2>&1 || python3 -m venv --without-pip "$VENV"; then
      if ! "$PY" -m pip --version >/dev/null 2>&1; then
        info "bootstrapping pip (ensurepip / get-pip)"
        "$PY" -m ensurepip --upgrade >/dev/null 2>&1 || { curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && "$PY" /tmp/get-pip.py -q; }
      fi
      ok "venv created: $VENV"
    else
      echo "FATAL: cannot create venv at $VENV" >&2; exit 1
    fi
  fi
fi

# 3. pip + python packages
core_ok()    { "$PY" -c 'import requests, bs4, lxml, markdownify' >/dev/null 2>&1; }
pw_mod_ok()  { "$PY" -c 'import playwright.sync_api' >/dev/null 2>&1; }
REQ_HASH="$( (cat "$REQ"; echo "$MODE") | sha256sum | cut -c1-16)"
if [ -x "$PY" ]; then
  if "$PY" -m pip --version >/dev/null 2>&1; then ok "pip: $("$PY" -m pip --version | cut -d' ' -f1-2)"; else bad "pip in venv"; MISSING=1; fi
  NEED_PIP=0
  core_ok && ok "python pkgs: requests bs4 lxml markdownify" || { bad "python core packages"; NEED_PIP=1; }
  if [ "$MODE" != core ]; then pw_mod_ok && ok "python pkg: playwright" || { bad "python package playwright"; NEED_PIP=1; }; fi
  if [ "$NEED_PIP" = 1 ]; then
    if [ "$MODE" = check ]; then MISSING=1
    else
      info "pip install -r requirements.txt"
      if [ "$MODE" = core ]; then grep -v '^playwright' "$REQ" > "$VENV/.req-core.txt"; RF="$VENV/.req-core.txt"; else RF="$REQ"; fi
      "$PY" -m pip install -q --disable-pip-version-check -r "$RF" || { echo "FATAL: pip install failed" >&2; exit 1; }
      core_ok || { echo "FATAL: core packages still not importable" >&2; exit 1; }
      ok "python packages installed"
      echo "$REQ_HASH" > "$VENV/.wxfetch-req-hash"
    fi
  fi
fi

# 4. Chromium (Playwright) — 浏览器降级路径
browser_ok() {
  "$PY" - <<'PYEOF' >/dev/null 2>&1
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox"])
    pg = b.new_page(); pg.set_content("<p>ok</p>"); assert pg.inner_text("p") == "ok"; b.close()
PYEOF
}
if [ "$MODE" != core ] && [ -x "$PY" ] && pw_mod_ok; then
  if browser_ok; then ok "chromium (playwright) launches headless"
  elif [ "$MODE" = check ]; then bad "chromium for playwright not ready"; MISSING=1
  else
    info "installing chromium via playwright (first time may take a few minutes)"
    if [ "$(id -u)" -eq 0 ]; then
      "$PY" -m playwright install --with-deps chromium >"$VENV/.playwright-install.log" 2>&1 || tail -5 "$VENV/.playwright-install.log" >&2
    else
      if [ -n "$SUDO" ]; then
        info "installing OS deps with sudo (playwright install-deps chromium)"
        $SUDO env "PATH=$PATH" "$PY" -m playwright install-deps chromium >/dev/null 2>&1 || info "install-deps failed (will still try)"
      else
        info "no root/sudo: skipping OS deps; chromium may fail to start if system libs are missing"
      fi
      "$PY" -m playwright install chromium >"$VENV/.playwright-install.log" 2>&1 || tail -5 "$VENV/.playwright-install.log" >&2
    fi
    if browser_ok; then ok "chromium ready"; else bad "chromium still cannot launch (browser fallback disabled; HTTP path still works)"; MISSING=1; fi
  fi
elif [ "$MODE" = core ]; then
  info "browser check skipped (--core)"
fi

if [ "$MISSING" = 0 ]; then echo "== READY ==" >&2; exit 0; else echo "== NOT READY (see [MISS] above; run: bash $DIR/setup.sh) ==" >&2; exit 1; fi
