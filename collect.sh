#!/usr/bin/env bash
# 兼容旧入口：等同于 content-capture collect。软链到别处也能找到真实目录。
CC_SELF="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}" 2>/dev/null \
  || printf '%s' "${BASH_SOURCE[0]}")"
exec "$(cd "$(dirname "$CC_SELF")" && pwd)/content-capture" collect "$@"
