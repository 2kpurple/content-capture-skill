#!/usr/bin/env python3
"""用 faster-whisper 把视频或音频转成文字。

用法:
  transcribe.py [--out-dir DIR] [--max-seconds N] [--language auto|zh|en|...] 输入文件

环境变量:
  CC_VENV            转录虚拟环境（本脚本建议用该环境的 python 启动）
  CC_WHISPER_MODEL   模型名（默认 small）或本地模型目录
  CC_LANGUAGE        默认识别语言；不设或设为 auto 时自动识别

退出码:
  0 成功；1 用法错误或找不到输入；3 依赖缺失（ffmpeg / ffprobe / faster-whisper）；
  4 ffprobe 读不了文件（损坏或不是音视频）；5 转录失败；7 没有音轨

输出（写在 --out-dir，默认与输入同一目录）:
  transcript.txt        带时间戳
  transcript_plain.txt  纯文本
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac"}
# 这些扩展也直接交给模型前，仍统一抽成 16k 单声道，避免采样率不一致。


def log(*a) -> None:
    print("[transcribe]", *a, file=sys.stderr, flush=True)


def run_ffmpeg(src: Path, dest: Path, max_seconds: float | None) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000",
    ]
    if max_seconds is not None and max_seconds > 0:
        cmd.extend(["-t", str(max_seconds)])
    cmd.append(str(dest))
    r = subprocess.run(cmd)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg 抽音频失败: {' '.join(cmd)}")


def resolve_model(name_or_path: str) -> str:
    p = Path(name_or_path).expanduser()
    if p.is_dir() and (p / "config.json").exists():
        return str(p)
    return name_or_path


def main() -> int:
    ap = argparse.ArgumentParser(description="faster-whisper 转录（cpu / int8 / vad_filter）")
    ap.add_argument("input", help="视频或音频文件")
    ap.add_argument("--out-dir", "-o", help="输出目录，默认与输入文件相同")
    ap.add_argument("--max-seconds", type=float, default=None, help="只转录前 N 秒（测试用，先用 ffmpeg 截取）")
    ap.add_argument(
        "--language",
        default=os.environ.get("CC_LANGUAGE") or "auto",
        help="识别语言，如 zh、en；auto 表示自动识别（默认读 CC_LANGUAGE，不设则 auto）",
    )
    ap.add_argument("--model", default=os.environ.get("CC_WHISPER_MODEL", "small"), help="模型名或本地目录（默认读 CC_WHISPER_MODEL）")
    args = ap.parse_args()
    language = (args.language or "").strip().lower()
    if language in {"", "auto", "none"}:
        language = None

    src = Path(args.input).expanduser().resolve()
    if not src.is_file():
        log(f"找不到输入文件: {src}")
        return 1
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped = out_dir / "transcript.txt"
    plain = out_dir / "transcript_plain.txt"

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            log(f"找不到 {tool}")
            return 3

    # 先用 ffprobe 看清文件：读不了（损坏、不是音视频）和确实没有音轨要分开报
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(src),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        err = " ".join((r.stderr or "").split())[-300:]
        log(f"ffprobe 读不了文件（可能损坏或不是音视频）: {src.name}  {err}")
        return 4
    stream_types = {line.strip().strip(",") for line in (r.stdout or "").splitlines() if line.strip()}
    if "audio" not in stream_types:
        log(f"输入没有音轨，无法转录: {src.name}（流: {', '.join(sorted(stream_types)) or '无'}）")
        return 7

    tmpdir = Path(tempfile.mkdtemp(prefix="cc-transcribe-"))
    wav = tmpdir / "audio_16k_mono.wav"
    try:
        log(f"抽音频: {src.name}" + (f" （仅前 {args.max_seconds} 秒）" if args.max_seconds else ""))
        run_ffmpeg(src, wav, args.max_seconds)

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            log("当前 Python 导入不了 faster-whisper。请用转录环境启动，例如:")
            log("  $CC_VENV/bin/python scripts/transcribe.py ...")
            return 3

        model_id = resolve_model(args.model)
        log(f"加载模型: {model_id}  device=cpu compute_type=int8")
        model = WhisperModel(model_id, device="cpu", compute_type="int8")
        segments, info = model.transcribe(
            str(wav),
            language=language,
            vad_filter=True,
            beam_size=5,
        )
        log(f"language={info.language}" + ("（自动识别）" if language is None else "") + f" duration={getattr(info, 'duration', None)}")

        lines = []
        texts = []
        for seg in segments:
            text = (seg.text or "").strip()
            if not text:
                continue
            line = f"[{seg.start:.2f}s -> {seg.end:.2f}s] {text}"
            lines.append(line)
            texts.append(text)
        stamped.write_text(("\n".join(lines) + ("\n" if lines else "")), encoding="utf-8")
        plain.write_text(("\n".join(texts) + ("\n" if texts else "")), encoding="utf-8")
        log(f"已写入 {stamped} 和 {plain}  segments={len(lines)}")
        return 0
    except Exception as e:
        log(f"转录失败: {e}")
        return 5
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
