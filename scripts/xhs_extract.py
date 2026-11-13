#!/usr/bin/env python3
"""只向 XHS-Downloader 要作品元数据和下载地址，不让它下载文件。

由 xhs_finish.py 在 CLI 没留下地址时调用。需要的环境变量：
  CC_XHS_DIR, CC_OUT, CC_URL, CC_EXTRACT_JSON
并在 XHS-Downloader 目录下用 `uv run python` 启动，以便导入 source。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

root = os.environ.get("CC_XHS_DIR") or os.getcwd()
sys.path.insert(0, root)

from source import XHS  # noqa: E402


async def main() -> None:
    async with XHS(
        work_path=os.environ["CC_OUT"],
        folder_name="Download",
        cookie="",
        download_record=False,
        language="zh_CN",
        note_format="",
        record_data=False,
    ) as xhs:
        data = await xhs.extract(os.environ["CC_URL"], download=False)
    Path(os.environ["CC_EXTRACT_JSON"]).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
