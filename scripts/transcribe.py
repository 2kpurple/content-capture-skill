#!/usr/bin/env python3
"""用 faster-whisper 把视频或音频转成文字。

用法:
  transcribe.py [--out-dir DIR] [--max-seconds N] [--language zh] 输入文件

环境变量:
  CC_VENV            转录虚拟环境（本脚本建议用该环境的 python 启动）
  CC_WHISPER_MODEL   模型名（默认 small）或本地模型目录

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
    ap = argparse.ArgumentParser(description="faster-whisper 转录（cpu / int8 / zh / vad_filter）")
    ap.add_argument("input", help="视频或音频文件")
    ap.add_argument("--out-dir", "-o", help="输出目录，默认与输入文件相同")
    ap.add_argument("--max-seconds", type=float, default=None, help="只转录前 N 秒（测试用，先用 ffmpeg 截取）")
    ap.add_argument("--language", default="zh", help="识别语言，默认 zh")
    ap.add_argument("--model", default=os.environ.get("CC_WHISPER_MODEL", "small"), help="模型名或本地目录（默认读 CC_WHISPER_MODEL）")
    args = ap.parse_args()

    src = Path(args.input).expanduser().resolve()
    if not src.is_file():
        log(f"找不到输入文件: {src}")
        return 1
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped = out_dir / "transcript.txt"
    plain = out_dir / "transcript_plain.txt"

    if shutil.which("ffmpeg") is None:
        log("找不到 ffmpeg")
        return 3

    def has_audio_stream(path: Path) -> bool:
        # 没有音轨时 ffmpeg -vn 会失败（例如无声动画视频）
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        return bool((r.stdout or "").strip())

    if not has_audio_stream(src):
        log(f"输入没有音轨，跳过识别: {src.name}")
        note = "[无音轨]\n"
        stamped.write_text(note, encoding="utf-8")
        plain.write_text("", encoding="utf-8")
        return 0

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
            language=args.language,
            vad_filter=True,
            beam_size=5,
        )
        log(f"language={info.language} duration={getattr(info, 'duration', None)}")

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
