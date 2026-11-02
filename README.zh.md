# video-factcheck

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![tests](https://github.com/vonavikon/video-factcheck/actions/workflows/tests.yml/badge.svg)](https://github.com/vonavikon/video-factcheck/actions/workflows/tests.yml)

[RU](README.ru.md) · [EN](README.md) · **中文** · [Español](README.es.md) · [Français](README.fr.md)

一款 Chrome 扩展（MV3），在你观看 YouTube 视频的同时做事实核查。扩展直接从页面读取字幕，服务器从中提取出可核查的论断并标注时间点，逐条核查（对照人工事实核查记录、网页搜索和科学文献），然后在播放器旁的面板里给出「属实 / 虚假 / 存疑」的判定。点击时间点跳转到论断出现的时刻；每条判定都附带来源和逐字引文。

「存疑」是正式判定，不是敷衍：它标记的是两次网页搜索结论不一致、或来源不足的论断。科学层刻意保守：一篇文章只有在切题且足够新时才能影响判定，而且永远不会给出「虚假」：最多把「属实」降为「存疑」。

![工作原理：YouTube 上的事实核查面板，论断卡片带判定和时间点，点击时间点跳转视频，每条判定附来源引文和权重](assets/concept.gif?v=v5)
视频版（10 秒，无声）：[how-it-works.mp4](assets/how-it-works.mp4?v=v5)
YouTube 实机演示（15 秒，无声）：[youtube-demo.mp4](assets/youtube-demo.mp4?v=v1)

## 工作原理

```text
[字幕级联]          直接从页面读取字幕；服务器端 yt-dlp 作为兜底
        ↓
[论断提取]          带时间点的可核查事实；观点归入「不可核查」
        ↓
[并行核查，三层]
        ├─ ClaimReview：现有人工核查（Google Fact Check Tools）
        ├─ sonar × 2：网页搜索；两次结论不一致 → 「存疑」
        └─ 科学层：Europe PMC → OpenAlex，基于摘要的 NLI 裁定
        ↓
[判定融合]          「属实 vs 科学反驳」冲突 → 「存疑」
        ↓
[YouTube 面板]      带时间点、来源和来源权重的卡片
```

- **字幕级联。** 2026 年 10 月 YouTube 关闭了字幕的直接访问，扩展改为按顺序尝试：页面世界的桥接（直播放器的 captionTracks）、`timed_text`、「转录」DOM 面板、带页面 Cookie 的 `get_transcript` 端点。全部失败时，服务器通过 yt-dlp 抓取字幕。
- **论断。** LLM 标注转录片段：逐字引文、类别、重要度。观点、预测和夸张归入「不可核查」，重复项按归一化哈希合并。
- **ClaimReview。** 如果论断已有人工核查（PolitiFact、Snopes、AFP、Provereno.media），直接展示其判定并注明媒体出处，不调用 LLM。这类卡片最先到达，不用等提取结束。
- **sonar × 2。** 每条核查用带网页搜索的模型跑两遍；结论不一致，结果为「存疑」。来源必须带逐字引文才能被采纳，编造的引文会被过滤。
- **科学层。** Europe PMC（医学/生物学，无需密钥）和 OpenAlex（全部学科）。一个廉价模型根据前 3 篇摘要裁定既有科学与论断的关系。影响门槛：文章必须直接切题、发表于 2015 年及以后（或是综述/元分析），并有逐字引文佐证，才能影响判定。
- **融合。** 「属实」被科学反驳时降为「存疑」，置信度「低」，理由合并展示。反方向上，科学从不提升判定。
- **面板。** 卡片信息流带判定筛选、时间轴上的判定分布图、置信度刻度，来源带权重高亮（「科学」「官方」）。

## 功能

- 「属实 / 虚假 / 存疑」判定，带时间点和置信度；点击时间点跳转到视频对应时刻
- 带切题度和时效性门槛的科学层（Europe PMC → OpenAlex），基于摘要裁定，必须附逐字引文
- 来源权重高亮（「科学」「官方」）基于域名信任度清单
- RU/EN 界面；判定说明的语言与界面语言分开设置
- 最近 50 个已核查视频的历史，保存在本地浏览器里
- 变形面板：折叠成带完成徽标的小圆点，核查进行时不挡屏幕

## 从源码安装

需要 Chrome/Edge 111+ 和 Python 3.12+。扩展未上架 Chrome Web Store，只能从源码安装。所有核查都走你自己的服务器（`127.0.0.1:8765`），API 密钥用你自己的。

### 服务器

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Linux/macOS: .venv/bin/pip
cd ..
cp .env.example .env
```

在 `.env` 里填入密钥：

- `VFC_LLM_KEY`：OpenAI 兼容服务商的密钥（默认 bothub：deepseek 提取论断并裁定 NLI，sonar 自带网页搜索给出判定）。必需。
- `VFC_SERPER_KEY`：你自己的 Serper 搜索密钥。
- `VFC_FACTCHECK_KEY`：Google Fact Check Tools 密钥；没有它 ClaimReview 层直接跳过。

Europe PMC 和 OpenAlex 无需密钥。启动服务器：

```bash
cd backend
.venv/Scripts/python -m videofactcheck.cli serve --port 8765
```

不用 Chrome 也可以从命令行核查单个视频：`.venv/Scripts/python -m videofactcheck.cli check "<视频 URL>"`。

### 扩展

1. 打开 `chrome://extensions`，启用「开发者模式」。
2. 「加载已解压的扩展程序」→ 本仓库的 `extension` 文件夹。
3. 打开任意 YouTube 视频：右侧出现「事实核查」面板。点击「核查视频」。

字幕约 10 秒到位，15 分钟视频的论断提取约需 2-4 分钟；判定随就绪陆续到达，不必干等：面板可以折叠，核查在后台继续。

## 架构

```text
extension/                    Chrome MV3
  content.js                  YouTube 上的面板：卡片、时间点分布图、折叠成圆点
  page-bridge.js              MAIN 世界的脚本：直播放器的 captionTracks 和 videoDetails
  background.js               service worker：与服务器通信
  options.html, account.html  设置（语言）和 50 条视频历史，存于 chrome.storage
backend/                      FastAPI + CLI
  videofactcheck/transcript.py       服务器端字幕兜底：yt-dlp、带自动字幕清理的 VTT 解析器
  videofactcheck/claims.py           带时间点的论断提取
  videofactcheck/factcheck_db.py     ClaimReview：现有人工核查
  videofactcheck/verdict.py          sonar × 2、置信度刻度、融合
  videofactcheck/plausibility.py     科学层：Europe PMC → OpenAlex、带引文的 NLI
  videofactcheck/trust.py            域名信任权重（白名单/黑名单）
  videofactcheck/store.py            SQLite：运行、判定、转录
  videofactcheck/server.py           面向扩展的 HTTP API（127.0.0.1:8765）
  videofactcheck/cli.py              `serve` 和 `check <url>`
  tests/                             72 个测试，pytest
```

扩展把从页面读到的字幕发给服务器（对 YouTube 的请求来自用户 IP，而非服务器 IP），判定就绪后陆续返回。

## 状态

个人项目。版本 0.9.1（2026 年 10 月），在真实视频上验证过。

项目靠真实使用的反馈逐步迭代：2026 年 10 月 YouTube 关闭字幕直接访问后，出现了字幕级联；ClaimReview 流水线（人工核查随首批提取结果先行到达）和判定按时间轴分层，来自 40 分钟长访谈的漫长核查；变形面板来自一句抱怨：「面板挡屏幕」。

限制：无字幕的视频会被拒绝（自动转写已列入计划）；不支持直播和 Shorts；单次核查最多给出 15 条判定，其余标记为「未核查」。

## 许可证

MIT，见 [LICENSE](LICENSE)。
