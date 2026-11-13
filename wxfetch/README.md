# wxfetch

微信公众号文章抓取脚本。用法：

```bash
./wxfetch "链接" --out "输出目录" --format both --download-images -q
bash setup.sh          # 幂等安装
bash setup.sh --check  # 只检查
```

方法出自「微信文章捕手」的 wechat-article-fetch（作者：铁柱AGI @cgnot996）。

本目录文件（`requirements.txt`、`setup.sh`、`wxfetch`、`scripts/wxfetch.py`）按原样收录，未改逻辑。

依赖的开源库：requests、Beautiful Soup 4、lxml、markdownify、Playwright。
