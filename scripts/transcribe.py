#!/usr/bin/env python3
"""用 faster-whisper 把视频或音频转成文字。

用法:
  transcribe.py [--out-dir DIR] [--max-seconds N] [--language auto|zh|en|...] 输入文件

环境变量:
  CC_VENV            转录虚拟环境（本脚本建议用该环境的 python 启动）
  CC_WHISPER_MODEL   模型名（默认 large-v3-turbo）或本地模型目录
  CC_MODELS_DIR      按模型名查找/下载模型的目录：$CC_MODELS_DIR/faster-whisper-<模型名>/
  CC_WHISPER_TEMPERATURE  解码温度。默认 faster-whisper 的回退序列 0,0.2,0.4,0.6,0.8,1.0
                     （先用 0，出现复读等质量问题才升温重试）；设成 0 则固定 0、不回退
  CC_LANGUAGE        默认识别语言；不设或设为 auto 时自动识别
  CC_ZH_PROMPT       中文转录的提示词，默认「以下是普通话的句子。」

中文统一输出简体：
  语言为 zh（指定 zh，或自动识别结果是 zh）时，用 language=zh 加简体提示词
  （initial_prompt）转录，再用 OpenCC t2s 把文字转成简体兜底。
  OpenCC 不在时照常转录，但会明确警告“可能含繁体”。

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


# 引导 Whisper 输出简体中文的提示词（本身用简体书写）。可用 CC_ZH_PROMPT 覆盖。
# 没用「……使用简体中文。」这类说明句：small 模型偶尔会把这半句原样写进文案。
ZH_PROMPT = os.environ.get("CC_ZH_PROMPT") or "以下是普通话的句子。"

_t2s = None


def to_simplified(text: str) -> str:
    """OpenCC 繁转简。OpenCC 不可用时抛 ImportError。"""
    global _t2s
    if _t2s is None:
        from opencc import OpenCC  # opencc-python-reimplemented（纯 Python）或官方 opencc

        try:
            _t2s = OpenCC("t2s")
        except Exception:
            _t2s = OpenCC("t2s.json")
    return _t2s.convert(text)


def opencc_available() -> bool:
    try:
        to_simplified("測")
        return True
    except Exception:
        return False


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
    """本地目录直接用；模型名先找 $CC_MODELS_DIR/faster-whisper-<名字>/，没有就下载到那里。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cc_model

    p, msg = cc_model.resolve(name_or_path)
    if p is not None:
        return str(p)
    if cc_model.looks_like_path(name_or_path) or cc_model.known_repo(name_or_path) is None:
        raise RuntimeError(f"模型不可用: {msg}")
    log(f"{msg}；现在下载（只需一次）")
    return str(cc_model.download(name_or_path))


def temperature_setting():
    raw = (os.environ.get("CC_WHISPER_TEMPERATURE") or "").strip()
    if not raw:
        return None  # 用 faster-whisper 默认的回退序列
    vals = [float(x) for x in raw.replace("，", ",").split(",") if x.strip()]
    return vals[0] if len(vals) == 1 else vals


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
    ap.add_argument("--model", default=os.environ.get("CC_WHISPER_MODEL") or "large-v3-turbo", help="模型名或本地目录（默认读 CC_WHISPER_MODEL，未设为 large-v3-turbo）")
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
        opts = dict(vad_filter=True, beam_size=5)
        temp = temperature_setting()
        if temp is not None:
            opts["temperature"] = temp
            log(f"temperature={temp}")
        if language == "zh":
            segments, info = model.transcribe(str(wav), language="zh", initial_prompt=ZH_PROMPT, **opts)
        else:
            # segments 是惰性生成器，info.language 在这里已经确定；
            # 自动识别成中文时丢掉这次结果，按 zh + 简体提示词重新转录（只多花一次语言检测）
            segments, info = model.transcribe(str(wav), language=language, **opts)
            if language is None and info.language == "zh":
                log("自动识别为中文，改用 language=zh + 简体提示词转录")
                segments, info = model.transcribe(str(wav), language="zh", initial_prompt=ZH_PROMPT, **opts)
        is_zh = info.language == "zh"
        log(f"language={info.language}" + ("（自动识别）" if language is None else "") + f" duration={getattr(info, 'duration', None)}")
        t2s = None
        if is_zh:
            if opencc_available():
                t2s = to_simplified
            else:
                log("警告: 没有 OpenCC（opencc-python-reimplemented），中文文案只靠提示词转简体，可能仍含繁体字。"
                    "请运行 content-capture setup 补装。")

        lines = []
        texts = []
        for seg in segments:
            text = (seg.text or "").strip()
            if t2s is not None:
                text = t2s(text)
            if not text:
                continue
            line = f"[{seg.start:.2f}s -> {seg.end:.2f}s] {text}"
            lines.append(line)
            texts.append(text)
        stamped.write_text(("\n".join(lines) + ("\n" if lines else "")), encoding="utf-8")
        plain.write_text(("\n".join(texts) + ("\n" if texts else "")), encoding="utf-8")
        log(f"已写入 {stamped} 和 {plain}  segments={len(lines)}" + ("  （已用 OpenCC 转为简体）" if t2s else ""))
        return 0
    except Exception as e:
        log(f"转录失败: {e}")
        return 5
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
