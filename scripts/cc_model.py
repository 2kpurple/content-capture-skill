#!/usr/bin/env python3
"""Whisper 模型定位、检查与下载（CTranslate2 格式，给 faster-whisper 用）。

CC_WHISPER_MODEL 可以是：
  - 本地模型目录（里面有 model.bin、config.json 等 CTranslate2 文件）；
  - 模型名（small、medium、large-v3、large-v3-turbo……），按名字去
    $CC_MODELS_DIR/faster-whisper-<名字>/ 找，找不到就从 Hugging Face 下载到这里。

用法（需用转录环境的 python 运行，要能 import faster_whisper / ctranslate2）:
  cc_model.py resolve  [模型]   输出本地目录（没下载时退出码 2）
  cc_model.py check    [模型]   检查已就绪且是可加载的 CTranslate2 模型（退出码 0/1）
  cc_model.py download [模型]   下载到 $CC_MODELS_DIR/faster-whisper-<名字>/（已存在则跳过）
不写模型时读 CC_WHISPER_MODEL。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_MODEL = "large-v3-turbo"


def models_dir() -> Path:
    d = os.environ.get("CC_MODELS_DIR") or os.path.join(
        os.path.expanduser("~"), ".local", "share", "content-capture", "models"
    )
    return Path(d).expanduser()


def is_model_dir(p: Path) -> bool:
    if not p.is_dir() or not (p / "model.bin").is_file() or not (p / "config.json").is_file():
        return False
    try:
        import ctranslate2

        return bool(ctranslate2.contains_model(str(p)))
    except ImportError:
        return True


def known_repo(name: str) -> str | None:
    try:
        from faster_whisper.utils import _MODELS
    except ImportError:
        return None
    return _MODELS.get(name)


def looks_like_path(value: str) -> bool:
    return os.sep in value or value.startswith(("~", ".")) or Path(value).expanduser().exists()


def local_dir_for(name: str) -> Path:
    return models_dir() / f"faster-whisper-{name}"


def resolve(value: str) -> tuple[Path | None, str]:
    """返回 (本地目录或 None, 说明)。"""
    if looks_like_path(value):
        p = Path(value).expanduser().resolve()
        if is_model_dir(p):
            return p, f"本地模型目录 {p}"
        return None, f"{p} 不是 CTranslate2 模型目录（需要 model.bin、config.json）"
    for cand in (local_dir_for(value), models_dir() / value):
        if is_model_dir(cand):
            return cand, f"{value} → {cand}"
    if known_repo(value) is None and "/" not in value:
        return None, f"未知模型名 {value}"
    return None, f"{value} 还没下载到 {local_dir_for(value)}（运行 content-capture setup 下载）"


def download(value: str) -> Path:
    if looks_like_path(value):
        p, msg = resolve(value)
        if p is None:
            raise SystemExit(msg)
        return p
    p, _ = resolve(value)
    if p is not None:
        return p
    repo = known_repo(value)
    if repo is None:
        raise SystemExit(f"未知模型名 {value}，没法自动下载；请改用本地目录")
    from faster_whisper.utils import download_model

    dest = local_dir_for(value)
    dest.mkdir(parents=True, exist_ok=True)
    print(f"下载 {repo} → {dest}", file=sys.stderr)
    download_model(value, output_dir=str(dest))
    if not is_model_dir(dest):
        raise SystemExit(f"下载完成但 {dest} 不是可用的模型目录")
    return dest


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"resolve", "check", "download"}:
        print(__doc__, file=sys.stderr)
        return 1
    value = argv[1] if len(argv) > 1 else (os.environ.get("CC_WHISPER_MODEL") or DEFAULT_MODEL)
    if argv[0] == "download":
        print(download(value))
        return 0
    p, msg = resolve(value)
    if argv[0] == "resolve":
        if p is None:
            print(msg, file=sys.stderr)
            return 2
        print(p)
        return 0
    # check
    print(msg)
    return 0 if p is not None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
