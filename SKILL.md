---
name: content-capture
description: 内容收录：把抖音、小红书、X、YouTube 视频链接或微信公众号文章链接，在本机下载、转录成文案并做内容解析，存成 Markdown 时用。
---
# content-capture（内容收录）

把一条链接变成「文案 + 内容解析」的本地 Markdown。全部用本机开源工具，不用付费 API。

脚本都在本技能目录（下文称 `$CC`，即本 SKILL.md 所在文件夹）。统一入口是 `$CC/content-capture`。用法细节见 `$CC/README.md`。

## 目录结构

- `content-capture`：统一 CLI 入口（collect / detect / setup / doctor / transcribe）。
- `collect.sh`：兼容壳，转发到 `content-capture collect`。
- `setup.sh`：幂等安装；`--check` 只自检。由 `content-capture setup` 调用，其中会再跑 `wxfetch/setup.sh`。
- `scripts/douyin.sh`、`douyin_parse.py`、`start_douyin_api.py`：抖音。
- `scripts/xhs.sh`、`xhs_finish.py`、`xhs_extract.py`：小红书。
- `scripts/ytdlp.sh`：X / YouTube。
- `scripts/transcribe.py`：语音转文字。
- `scripts/extract_url.py`、`scripts/lib.sh`：从分享口令抽 URL，并识别平台。
- `wxfetch/`：公众号抓取，原样来自「微信文章捕手」的 wechat-article-fetch（作者：铁柱AGI @cgnot996）。由 `collect` 在识别为公众号后自动调用。

大仓库（TikTokDownloader、XHS-Downloader）、虚拟环境、Whisper 模型、cookie 都不放进技能文件夹，由 `content-capture setup` 装到工具目录。

## 用到的开源库

| 用途 | 开源库 | 地址 |
|---|---|---|
| 抖音下载 | TikTokDownloader（DouK-Downloader） | https://github.com/JoeanAmier/TikTokDownloader |
| 小红书下载 | XHS-Downloader | https://github.com/JoeanAmier/XHS-Downloader |
| X / YouTube 下载 | yt-dlp | https://github.com/yt-dlp/yt-dlp |
| 抽音频、转格式 | FFmpeg | https://ffmpeg.org |
| 语音转文字 | faster-whisper（基于 CTranslate2 + OpenAI Whisper 模型） | https://github.com/SYSTRAN/faster-whisper |
| 音频解码 | PyAV（用 13.x，19.x 与 faster-whisper 1.2 不兼容） | https://github.com/PyAV-Org/PyAV |
| 公众号抓取 | requests、Beautiful Soup 4、lxml、markdownify、Playwright | https://github.com/psf/requests 、https://www.crummy.com/software/BeautifulSoup/ 、https://github.com/lxml/lxml 、https://github.com/matthewwithanm/python-markdownify 、https://github.com/microsoft/playwright-python |
| Python 环境管理 | uv | https://github.com/astral-sh/uv |

## 1. 环境

环境变量（都有默认值，本机已有工具时先导出，避免重复下载）：
- `CC_TOOLS_DIR`：大仓库所在目录，默认 `~/.local/share/content-capture/tools`；也可分别用 `CC_TIKTOK_DIR`、`CC_XHS_DIR`。
- `CC_VENV`：转录虚拟环境，默认 `~/.local/share/content-capture/venv`。
- `CC_WHISPER_MODEL`：Whisper 模型名或本地路径，默认 `small`。
- `CC_DOUYIN_API`：TikTokDownloader Web API 地址，默认 `http://127.0.0.1:5555`。
- `WXFETCH_VENV`：公众号抓取的虚拟环境，默认 `~/.local/share/wxfetch/venv`。

首次使用运行 `$CC/content-capture setup`，之后每次先 `$CC/content-capture doctor`，非 0 就重新跑安装。抖音需要 cookie，由使用者自己写进 TikTokDownloader 的 `Volume/settings.json`；小红书、X、YouTube、公众号都不需要登录。

## 2. 收录

```bash
$CC/content-capture collect <链接> [输出目录]
$CC/content-capture collect --max-seconds 60 <链接> [输出目录]   # 只转录前 60 秒，测试用
$CC/content-capture collect --skip-transcribe <链接> [输出目录]
$CC/collect.sh <链接> [输出目录]   # 等价于 content-capture collect
```

`detect` 根据链接域名（或分享口令里的第一个 URL）判断平台：`douyin`、`xhs`、`x`、`youtube`、`wechat`，其余为 `unknown`（含 B 站，暂不支持）。公众号也走 `collect`，识别后自动调用 wxfetch。

stdout 打印一段 JSON 摘要（也存为 `<输出目录>/summary.json`），含平台、标题、作者、文件路径、状态。退出码：0 成功，1 用法错误，2 不支持的链接，3 依赖缺失，4 下载失败，5 转录失败，6 公众号抓取失败，10 工具未就绪。非 0 就如实告诉使用者，不编内容。

各平台做法（脚本已实现，排障时参考）：
- **抖音**：TikTokDownloader Web API。没启动时用 `scripts/start_douyin_api.py` 非交互启动。`POST /douyin/share` 拿作品 ID，`POST /douyin/detail` 取 `data.downloads`，curl 带浏览器 UA 和 `Referer: https://www.douyin.com/` 下载。不调用 `POST /settings`，不改它的全局配置。直接用 yt-dlp 下抖音常被 403。
- **小红书**：XHS-Downloader（`-l zh_CN --note_format all --folder_mode true --record_data true`）。xhscdn 的 `http://` 地址会返回 500，脚本会改成 `https://` 用 curl 补下。链接要保留 `xsec_token` 参数。yt-dlp 下小红书常报「No video formats」。
- **X**：yt-dlp 默认参数。有的视频没有音轨，转录会写 `[无音轨]`。
- **YouTube**：yt-dlp 加 `--extractor-args "youtube:player_client=android" -f 18`，避开 429。
- **公众号**：`collect` 调用 `wxfetch`，先走 HTTP，失败就换 Playwright 无头浏览器；输出 `article.md`（带标题、公众号、作者、发布时间）、`article.json`、`images/`。它自己的退出码：4 反爬（稍后重试一次），5 已删除，6 只能在微信里打开，7 账号迁移，8 付费内容。多篇逐篇跑，篇间停一两秒。
- **转录**：faster-whisper，默认模型 `small`，CPU、int8、`vad_filter=True`；语言默认抖音/小红书 `zh`、X/YouTube 自动识别，可用 `--language auto|zh|en|...` 覆盖。输出带时间戳的 `transcript.txt` 和纯文本。也可用 `content-capture transcribe <音频> [--max-seconds N] [--language L]` 单独转录。抖音图集、小红书图文只存图片和文案（summary 里 `kind: images`），不转录；文件损坏或没有音轨时 collect 报失败（退出码 5）。

## 3. 存档

每条一个 Markdown，文件名 `日期-平台-标题.md`，内容：
- 标题、来源平台、原链接、作者/账号（公众号加发布时间）
- 钩子（视频前 3 秒或文章开头）
- 结构拆解
- 可复用的表达与节奏
- 可以借鉴改写的方向（只为做自己的原创）
- 文案全文：视频转录原话照记，不润色，听不清处标「[听不清]」，同音错字另列「可能的识别错误」；公众号保留原文。

聊天里只给解析要点和文件路径，长文案不全贴。

## 规则
- 链接失效、要登录、下载失败就直说，不编内容。
- 只做收录和解析，不外发、不代发、不评论、不私信，不教搬运或洗稿。
- 不要把 cookie、大仓库、模型、虚拟环境复制进技能文件夹。
- 下载完删掉不需要的中间文件。
