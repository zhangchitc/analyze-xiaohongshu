# analyze-xiaohongshu

> Analyze a Xiaohongshu (小红书/RED) account by scraping its notes and covers, then generating a comprehensive methodology report across 7 dimensions.

A Claude Code skill that scrapes a Xiaohongshu account's profile, downloads cover images, and produces a structured methodology report with an interactive dashboard.

## Installation

```bash
cd ~/.claude/skills
git clone https://github.com/zhangchitc/analyze-xiaohongshu.git analyze-xiaohongshu
```

Install dependencies:

```bash
cd analyze-xiaohongshu
pip3 install -r scripts/requirements.txt
playwright install chromium
```

## Usage

In Claude Code, use:

```
/analyze-xiaohongshu <xiaohongshu-url-or-user-id>
```

Or describe naturally:

- "分析小红书账号 https://www.xiaohongshu.com/user/profile/xxx"
- "爬取小红书 xxx 的数据并生成报告"
- "analyze xiaohongshu account xxx"
- "生成账号方法论报告"

## How it works

1. **Scrape** — Opens a Chromium browser, logs in via QR code (first time), scrolls the profile page to collect up to 100 note cards (title, cover image, likes, content type)
2. **Download covers** — Saves cover images locally for visual analysis
3. **Analyze** — Claude reads the data and cover images, performing analysis across 7 dimensions:
   - Account overview & stats
   - Top 10 hit notes breakdown
   - Title pattern analysis
   - Cover image visual analysis
   - Content topic clustering
   - Format comparison (video vs image)
   - Replicable methodology summary
4. **Generate report** — Outputs a detailed Markdown report (`report.md`) and structured JSON (`analysis.json`)
5. **Build dashboard** — Generates an interactive HTML dashboard with charts and visualizations

## Requirements

- Python 3.8+
- [Playwright](https://playwright.dev/python/) (with Chromium)
- Claude Code with skill support
