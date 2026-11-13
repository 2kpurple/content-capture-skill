#!/usr/bin/env python3
"""非交互启动 TikTokDownloader Web API。

在 TikTokDownloader 项目目录下执行：
    uv run python /path/to/start_douyin_api.py

或设置 CC_TIKTOK_DIR 后从任意目录执行。

这样做是为了绕过交互式菜单和免责声明提示。
不修改 Volume/settings.json，也不调用 POST /settings。
"""
from __future__ import annotations

import os
import sys
from asyncio import CancelledError, run

root = os.environ.get("CC_TIKTOK_DIR") or os.getcwd()
root = os.path.abspath(root)
os.chdir(root)
if root not in sys.path:
    sys.path.insert(0, root)

from src.application import TikTokDownloader  # noqa: E402


async def main() -> None:
    async with TikTokDownloader() as downloader:
        downloader.project_info()
        downloader.check_config()
        await downloader.check_settings(False)
        # 直接进入 Web API，不走 main_menu / disclaimer 交互。
        await downloader.server()


if __name__ == "__main__":
    try:
        run(main())
    except (KeyboardInterrupt, CancelledError, SystemExit):
        pass
