# content-capture（内容收录）

把一条链接变成「文案 + 内容解析」的本地材料。本目录只放我们自己的小脚本，不包含第三方大仓库、虚拟环境、Whisper 模型或 cookie。

统一入口是 `content-capture`。配套说明在同目录的 `SKILL.md`（收录格式与解析规则）。

## 开源库

| 用途 | 开源库 | 地址 |
|---|---|---|
| 抖音下载 | TikTokDownloader（DouK-Downloader） | https://github.com/JoeanAmier/TikTokDownloader |
| 小红书下载 | XHS-Downloader | https://github.com/JoeanAmier/XHS-Downloader |
| X / YouTube 下载 | yt-dlp | https://github.com/yt-dlp/yt-dlp |
| 抽音频、转格式 | FFmpeg | https://ffmpeg.org |
| 语音转文字 | faster-whisper（基于 CTranslate2 + OpenAI Whisper） | https://github.com/SYSTRAN/faster-whisper |
| 音频解码 | PyAV（必须用 13.x；19.x 与 faster-whisper 1.2 不兼容） | https://github.com/PyAV-Org/PyAV |
| 公众号抓取 | requests、Beautiful Soup 4、lxml、markdownify、Playwright | https://github.com/psf/requests 、https://www.crummy.com/software/BeautifulSoup/ 、https://github.com/lxml/lxml 、https://github.com/matthewwithanm/python-markdownify 、https://github.com/microsoft/playwright-python |
| Python 环境管理 | uv | https://github.com/astral-sh/uv |

公众号脚本在 `wxfetch/`，方法出自「微信文章捕手」的 wechat-article-fetch（作者：铁柱AGI @cgnot996）。详见 `wxfetch/README.md`。由 `content-capture collect` 在识别为公众号后自动调用。

TikTokDownloader 和 XHS-Downloader 由 `content-capture setup` 克隆到工具目录，不要把整个仓库拷进本技能文件夹。

## 环境变量

| 变量 | 默认 | 含义 |
|---|---|---|
| `CC_TOOLS_DIR` | `~/.local/share/content-capture/tools` | 工具根目录（其下是 `TikTokDownloader`、`XHS-Downloader`）。本机已有时请指到现成目录，不要重复 clone。 |
| `CC_TIKTOK_DIR` | `$CC_TOOLS_DIR/TikTokDownloader` | 抖音工具目录（可单独覆盖） |
| `CC_XHS_DIR` | `$CC_TOOLS_DIR/XHS-Downloader` | 小红书工具目录（可单独覆盖） |
| `CC_VENV` | `~/.local/share/content-capture/venv` | 转录虚拟环境（faster-whisper==1.2.1、av==13.1.0、opencc-python-reimplemented==0.1.7） |
| `CC_WHISPER_MODEL` | `small` | Whisper 模型名，或本地模型目录 |
| `CC_DOUYIN_API` | `http://127.0.0.1:5555` | TikTokDownloader Web API 地址 |
| `CC_ZH_PROMPT` | `以下是普通话的句子。` | 中文转录时给 Whisper 的简体提示词（initial_prompt） |
| `CC_MAX_SECONDS` | （空） | 给 `content-capture collect` 的默认转录截取秒数 |
| `WXFETCH_VENV` | `~/.local/share/wxfetch/venv` | 公众号脚本自己的虚拟环境（见 wxfetch/setup.sh） |
| `CC_OUTPUT_ROOT` | `./content-capture-out` | 收录根目录：collect 默认素材目录、正文 Markdown、总索引都在这里 |
| `CC_INDEX_FILE` | `$CC_OUTPUT_ROOT/索引.md` | 总索引文件（`--index` 可单次覆盖） |
| `CC_CONFIG` | `~/.config/content-capture/config.sh` | 本机配置文件（可选，普通 shell 赋值），只补没导出的变量 |

抖音 cookie 只放在 TikTokDownloader 自己的 `Volume/settings.json` 里，本技能不会复制、不会改这个文件，也不会调用 `POST /settings`。

## 用法

先安装或自检（幂等）：

```bash
# 本机已有工具和模型时，先导出路径再执行
export CC_TOOLS_DIR=/path/to/tools
export CC_VENV=/path/to/venv          # 若没有，就让 setup 建默认环境
export CC_WHISPER_MODEL=/path/to/faster-whisper-small

./content-capture setup            # 检查并补齐 yt-dlp、ffmpeg、uv、转录环境、两个下载器、wxfetch
./content-capture doctor           # 只检查依赖、模型、抖音 API、wxfetch 虚拟环境；缺东西时退出码 1
```

收录一条链接（视频会下载并转录，公众号自动走 wxfetch）：

```bash
./content-capture collect <链接> [输出目录]
./content-capture collect --max-seconds 60 <链接> [输出目录]   # 长视频可只转录前 60 秒做连通性测试
./content-capture collect --skip-transcribe <链接> [输出目录]  # 只下载不转录
./content-capture collect --index <索引.md> <链接>             # 本次登记到指定索引
./collect.sh <链接> [输出目录]                                 # 兼容壳，等价于 collect
```

只判断平台（stdout 仅输出 `douyin`、`xhs`、`x`、`youtube`、`wechat` 或 `unknown`；也可从分享口令里抽第一个 URL）：

```bash
./content-capture detect <链接或分享口令>
```

## 总索引 `索引.md`

收录根目录下维护一张总索引表，固定 5 列：

| 标题 | 来源（平台） | 标签 | 摘要 | 文档链接 |
|---|---|---|---|---|

- **来源（平台）** 写成 `[抖音](<原链接>)`，原链接就是这一行的主键。
- **文档链接** 是相对索引文件位置的链接，指向这一条的正文 `日期-平台-标题.md`；中文、空格放在 `<>` 里，`%`、`#`、`?`、`|` 会百分号编码，按 CommonMark / GFM 规则解析后都能直接点开。
- 标题、标签、摘要里的 `|` 会转义成 `\|`，换行写成 `<br>`。
- 同一原链接或同一正文文档只占一行，再登记只会更新。写入先写临时文件再原子替换，并加文件锁，多个任务同时写也不会丢行。表格外手写的内容会保留。

`collect` 成功后会按原链接预留一行（标签、摘要为空），summary.json 里的 `doc` 是正文要写到的路径。写好正文后用 `index add` 补上标签和摘要：

```bash
./content-capture index add --doc <正文.md> --title <标题> --platform <douyin|xhs|x|youtube|wechat> \
  --tags "标签1,标签2" --summary "一两句摘要" [--url <原链接>] [--index <索引.md>]
./content-capture index path [--index <索引.md>]   # 输出当前使用的索引文件
```

索引位置的优先级：`--index` > `CC_INDEX_FILE` > `$CC_OUTPUT_ROOT/索引.md`。想让某台机器固定用某个目录，写进 `~/.config/content-capture/config.sh`，例如 `CC_OUTPUT_ROOT=/path/to/内容收录`。

单独转录本地音频或视频（默认模型 `small`）：

```bash
./content-capture transcribe <音频或视频> [--max-seconds N] [--language auto|zh|en|...]
```

结束时在 stdout 打印 JSON 摘要（平台、标题、作者、文件路径、状态），完整副本在 `<输出目录>/summary.json`。失败会带 `error_code` 和 `message`，退出码非 0。

`collect` 退出码：`0` 成功；`1` 用法错误；`2` 不支持的链接；`3` 依赖缺失；`4` 下载失败；`5` 转录失败；`6` 公众号抓取失败；`10` 工具未就绪。

也可以单独调用各底层脚本：

```bash
scripts/douyin.sh  <抖音链接>   <输出目录>
scripts/xhs.sh     <小红书链接> <输出目录>
scripts/ytdlp.sh   <X|YouTube 链接> <输出目录>
$CC_VENV/bin/python scripts/transcribe.py [--out-dir DIR] [--max-seconds N] [--language auto|zh|en|...] 输入文件
```

## 各平台要点

- **抖音**：若 `127.0.0.1:5555` 未启动，会在 TikTokDownloader 目录后台执行非交互的 Web API（`scripts/start_douyin_api.py`，不走交互菜单）。然后 `POST /douyin/share` 拿作品 ID，`POST /douyin/detail` 取 `data.downloads`，再用 curl（浏览器 UA + `Referer: https://www.douyin.com/`）下到输出目录，并写 `meta.json`。不要调用 `POST /settings`。
- **小红书**：`uv run main.py -l zh_CN -u 链接 --work_path 输出目录 --note_format all --folder_mode true`。视频若因 `http://` xhscdn 返回 500 而失败，会改成 `https://` 用 curl 补下。
- **X**：普通 `yt-dlp`，带 `--write-info-json`。
- **YouTube**：`--extractor-args youtube:player_client=android -f 18`。
- **公众号**：由 `collect` 调用 `wxfetch/`，不需要登录。

转录使用 faster-whisper，默认模型 `small`：`device=cpu`、`compute_type=int8`、`vad_filter=True`。语言：collect 对抖音、小红书默认 `zh`，对 X、YouTube 默认自动识别；可用 `--language`（或环境变量 `CC_LANGUAGE`）覆盖，`auto` 表示自动识别。

**中文统一输出简体**：faster-whisper small 常把中文转成繁体。现在语言是 `zh` 时（直接指定，或自动识别结果是 `zh`——先用一次语言检测，再按 `zh` + 简体提示词正式转录），会传 `language=zh` 和 `initial_prompt`（默认「以下是普通话的句子。」，可用 `CC_ZH_PROMPT` 改），转完再用 OpenCC t2s 把每一段文字转成简体，`transcript.txt` 和 `transcript_plain.txt` 都会处理。OpenCC 用纯 Python 的 `opencc-python-reimplemented`，Linux、macOS 都不需要系统库，由 `content-capture setup` 装进转录环境，`doctor` 会检查。缺 OpenCC 时转录照常完成，但会在日志里明确警告「可能仍含繁体字」。英文等其他语言不受影响。

抖音图集、小红书图文只保存图片和文案，不转录。文件损坏、ffprobe 读不了或没有音轨时，collect 以退出码 5 报失败。输入可以是视频或音频；必要时先用 ffmpeg 抽 16 kHz 单声道。输出 `transcript.txt`（带时间戳）和 `transcript_plain.txt`（纯文本）。

## 鸣谢

本项目只是把下面这些优秀的开源项目和方法串成一个收录流程，核心能力都来自它们。感谢各位作者和贡献者：

- [TikTokDownloader（DouK-Downloader）](https://github.com/JoeanAmier/TikTokDownloader)，作者 [JoeanAmier](https://github.com/JoeanAmier)：抖音作品解析与下载。
- [XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)，作者 [JoeanAmier](https://github.com/JoeanAmier)：小红书笔记与视频下载。
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)，yt-dlp 社区：X、YouTube 视频下载。
- [FFmpeg](https://ffmpeg.org)：抽取音频、转换格式。
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)，SYSTRAN：本地语音转文字。
- [Whisper](https://github.com/openai/whisper)，OpenAI：语音识别模型。
- [CTranslate2](https://github.com/OpenNMT/CTranslate2)，OpenNMT：faster-whisper 的推理引擎。
- [PyAV](https://github.com/PyAV-Org/PyAV)：音频解码。
- 微信公众号抓取脚本 `wxfetch/`：来自「微信文章捕手」的 wechat-article-fetch，作者 铁柱AGI（X：[@cgnot996](https://x.com/cgnot996)，公众号同名）。
- [Requests](https://github.com/psf/requests)、[Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/)、[lxml](https://github.com/lxml/lxml)、[markdownify](https://github.com/matthewwithanm/python-markdownify)、[Playwright for Python](https://github.com/microsoft/playwright-python)：公众号网页请求、解析、转 Markdown 和浏览器降级。
- [uv](https://github.com/astral-sh/uv)，Astral：Python 环境与依赖管理。

各项目的版权和许可证归原作者所有，使用时请遵守各自的许可证。
