# analyze-xiaohongshu

> 爬取小红书账号的笔记和封面图，自动生成涵盖 7 大维度的账号方法论报告。

一个 Claude Code 技能，可以爬取小红书账号主页、下载封面图，并生成结构化的方法论报告和交互式数据看板。

## 安装

```bash
cd ~/.claude/skills
git clone https://github.com/zhangchitc/analyze-xiaohongshu.git analyze-xiaohongshu
```

安装依赖：

```bash
cd analyze-xiaohongshu
pip3 install -r scripts/requirements.txt
playwright install chromium
```

## 使用方式

在 Claude Code 中输入：

```
/analyze-xiaohongshu <小红书链接或用户ID>
```

或者用自然语言描述：

- "分析小红书账号 https://www.xiaohongshu.com/user/profile/xxx"
- "爬取小红书 xxx 的数据并生成报告"
- "生成账号方法论报告"

## 工作原理

1. **爬取数据** — 打开 Chromium 浏览器，首次使用需扫码登录，滚动主页收集最多 100 条笔记卡片（标题、封面图、点赞数、内容类型）
2. **下载封面** — 将封面图保存到本地，用于视觉分析
3. **七维分析** — Claude 读取数据和封面图，从 7 个维度进行深度分析：
   - 账号概览与核心数据
   - Top 10 爆款笔记拆解
   - 标题模式分析
   - 封面图视觉分析
   - 内容选题聚类
   - 内容形式对比（视频 vs 图文）
   - 可复制的方法论总结
4. **生成报告** — 输出详细的 Markdown 报告（`report.md`）和结构化 JSON 数据（`analysis.json`）
5. **构建看板** — 生成包含图表和可视化的交互式 HTML 数据看板

## 环境要求

- Python 3.8+
- [Playwright](https://playwright.dev/python/)（含 Chromium）
- 支持 Skill 的 Claude Code
