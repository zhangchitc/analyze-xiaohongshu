---
name: analyze-xiaohongshu
description: Analyze a Xiaohongshu (小红书/RED) account by scraping its notes and covers, then generating a comprehensive methodology report across 7 dimensions. Use when the user provides a Xiaohongshu account URL or user ID and asks to analyze the account, reverse-engineer its strategy, or generate a methodology report. Triggers on phrases like "分析小红书账号", "爬取小红书", "analyze xiaohongshu account", "生成账号方法论报告".
---

# analyze-xiaohongshu

Scrape a Xiaohongshu account's notes and cover images, then produce a structured methodology report.

## Workflow

### Step 1: Parse input

Accept either format:
- Full URL: `https://www.xiaohongshu.com/user/profile/<ID>`
- Raw user ID string

Extract the account ID using the pattern `/user/profile/([a-zA-Z0-9]+)`.

### Step 2: Environment check

```bash
python3 --version          # must be 3.8+
pip3 show playwright       # check if installed
```

If playwright is missing:
```bash
pip3 install playwright && playwright install chromium
```

### Step 3: Run the scraper

The scraper is at `scripts/scraper.py` (relative to this skill directory). Find its absolute path first.

```bash
python3 <skill_dir>/scripts/scraper.py <account_url_or_id>
```

**Behavior:**
- Opens a visible Chromium browser
- If no saved cookie exists or cookie is expired → waits for user to manually scan QR code and log in (up to 3 minutes)
- Saves cookie to `data/cookies.json` for reuse
- Scrolls the profile page to collect up to 100 note cards — **no detail page visits**
- For each card, extracts: note ID, URL, title, cover image URL, like count, content type (video/image)
- Downloads cover images to `covers/`
- Supports resume: skips notes already in `data/<account_id>/notes.json`
- Saves data to `data/<account_id>/` inside the skill directory

**Output paths:**
```
<skill_dir>/data/
├── cookies.json
└── <account_id>/
    ├── profile.json
    ├── notes.json        # fields: note_id, url, title, cover_url, likes, type, cover_local_path
    └── covers/
        └── <note_id>.jpg
```

### Step 4: Load data

After the scraper finishes, read the JSON files:

```python
import json
profile = json.load(open("data/<account_id>/profile.json"))
notes   = json.load(open("data/<account_id>/notes.json"))
```

### Step 5: Analyze covers (batched visual analysis)

Read cover images in batches of 5–10 using the Read tool (images). Prioritize covers from the top 20% notes by likes first, then the rest for comparison.

Engagement score per note = `likes` (only metric available from profile cards)

### Step 6: Generate the report

Write a Markdown report to `data/<account_id>/report.md`. Include all 7 dimensions below.

### Step 6.5: Generate analysis.json

After the report, generate `data/<account_id>/analysis.json` with structured data extracted from your analysis. The dashboard (`scripts/dashboard.py`) **requires** this file.

```json
{
  "account_id": "<account_id>",
  "generated_at": "YYYY-MM-DD",
  "topic_categories": {
    "<category_name>": ["keyword1", "keyword2", ...]
  },
  "title_formulas": [
    {
      "name": "公式名称",
      "pattern": "regex_pattern",
      "template": "模板描述",
      "trigger": "触发机制",
      "color": "#hex",
      "examples": ["示例标题1", "示例标题2"]
    }
  ],
  "cloud_keywords": ["word1", "word2", ...],
  "radar_dimensions": ["收藏潜力", "分享潜力", "时效性", "专业门槛", "变现潜力"],
  "radar_scores": {
    "<category_name>": [0-100, 0-100, 0-100, 0-100, 0-100]
  },
  "strategies": [
    {
      "title": "策略标题",
      "body": "策略详细说明",
      "action": "具体行动建议"
    }
  ],
  "top10_note_ids": ["8-char-prefix", ...],
  "top10_analysis": [
    { "note_id_prefix": "8-char-prefix", "success_factors": "该笔记的成功因素拆解" }
  ],
  "hit_patterns": [
    "爆款共性总结（如：同一公式贡献X%总赞）"
  ],
  "title_hit_vs_miss": {
    "dimensions": ["对比维度1", "对比维度2", ...],
    "hit": ["爆款特征1", "爆款特征2", ...],
    "miss": ["普通特征1", "普通特征2", ...]
  },
  "cover_analysis": {
    "styles": [
      { "name": "风格名", "count": 4, "traits": "风格特征描述", "performance": "high|medium|mixed|low" }
    ],
    "hit_cover_patterns": ["爆款封面共性1", "爆款封面共性2"],
    "template_suggestion": "推荐的封面模板描述"
  },
  "category_insights": {
    "<category>": "该类别的定性分析（优势、弱点、建议）"
  },
  "format_comparison": {
    "video_avg_likes": 0,
    "image_avg_likes": 0,
    "video_total_likes_pct": 0,
    "insight": "视频vs图文总结",
    "per_category": [
      { "category": "类别名", "best_format": "视频|图文|均可", "reason": "原因" }
    ]
  },
  "content_formulas_recap": [
    { "label": "A 公式名", "template": "公式模板" }
  ],
  "action_plan": {
    "this_week": ["本周行动1", "本周行动2"],
    "this_month": ["本月行动1"],
    "long_term": ["长期方向1"]
  }
}
```

**Field guidelines:**
- `topic_categories`: 3-6 categories with 5-20 keywords each, derived from the account's actual content themes
- `title_formulas`: 4-8 formulas with valid regex patterns, derived from the account's title patterns
- `cloud_keywords`: 20-40 high-frequency keywords from the account's titles
- `radar_scores`: One entry per topic category, scores 0-100 for each of the 5 radar dimensions
- `strategies`: 3-5 actionable strategies from the report's dimension 7
- `top10_note_ids`: First 8 characters of the top 10 notes' IDs (by likes)
- `top10_analysis`: Per-note success factor breakdown for each top 10 note, matched by `note_id_prefix`
- `hit_patterns`: 1-3 bullet points summarizing the key patterns shared by hit content
- `title_hit_vs_miss`: Multi-dimension comparison table of hit vs miss title characteristics
- `cover_analysis`: Cover style distribution, hit cover patterns, and template suggestion
- `category_insights`: One qualitative paragraph per topic category (strengths, weaknesses, recommendations)
- `format_comparison`: Video vs image performance comparison with per-category recommendations
- `content_formulas_recap`: 3-5 quick-reference content formulas (label + template)
- `action_plan`: Time-bound action items split into `this_week`, `this_month`, `long_term`

### Step 7: Generate the dashboard

Run the dashboard generator to produce an interactive HTML dashboard:

```bash
python3 <skill_dir>/scripts/dashboard.py <account_id>
```

This reads `data/<account_id>/analysis.json` (required) along with `profile.json` and `notes.json`, and outputs `data/<account_id>/dashboard.html`.

Note on data availability: the scraper collects card-level data only (title, likes, cover, type). Hashtags and publish dates are not visible on profile cards and are excluded.

---

## Report Structure (7 Dimensions)

### 1. 账号概览
- 昵称、简介、粉丝量级、内容类型定位
- 核心统计：总笔记数、平均点赞、点赞中位数
- 视频 vs 图文比例

### 2. 爆款笔记分析（Top 10）
- 按点赞数降序排列
- 每篇列出：标题、点赞数、内容类型、成功因素拆解
- 爆款定义：点赞量排名前 20% 的笔记

### 3. 标题分析
- 标题长度分布与最佳长度区间
- 高频词和句式模式（如"xx个方法"、"千万别xx"、提问式等）
- 爆款 vs 普通标题的差异对比
- 可复用的标题公式总结（至少 3 个）

### 4. 封面图分析（视觉分析）
- 风格类型分布（实拍 / 设计图 / 截图 / 对比图等）
- 配色特征、文字使用规律、构图规律
- 爆款封面的共性特征
- 可复用的封面模板建议

### 5. 内容选题分析
- 主题分类及各类占比（基于标题文本聚类）
- 各类别的平均点赞表现
- 最受欢迎的选题方向

### 6. 内容形式分析
- 图文 vs 视频的比例与点赞表现对比
- 哪种形式更受该账号受众欢迎

### 7. 可复制的方法论总结
- 该账号的核心增长策略（3-5条）
- 可直接复用的内容公式
- 具体行动建议清单（可执行的 to-do list）

---

## Error Handling

- **Scraper gets no notes**: Check that `section.note-item` elements exist on the profile page. If not, the scraper falls back to `a[href*="/explore/"]` links.
- **Cookie expired**: Delete `data/cookies.json` and rerun the scraper to trigger a fresh login.
- **Partial data**: If the scraper was interrupted, rerun it — it will skip already-downloaded covers.
- **Missing cover images**: Proceed with analysis using available covers; note which notes lack covers.
- **Anti-bot detection**: The scraper stays on the profile page only. If detection still occurs, increase `DELAY_MIN`/`DELAY_MAX` in `scraper.py`.
