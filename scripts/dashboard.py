#!/usr/bin/env python3
"""
小红书账号分析看板生成器
生成自包含的 HTML 数据看板（引用本地封面图）
用法: python3 dashboard.py <account_id>
输出: data/<account_id>/dashboard.html
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
DATA_DIR = BASE_DIR / "data"


def load_analysis(account_id: str) -> dict:
    """加载 analysis.json，缺失则报错退出"""
    path = DATA_DIR / account_id / "analysis.json"
    if not path.exists():
        print(f"错误: 缺少分析文件: {path}")
        print(f"请先运行 analyze-xiaohongshu skill 生成 analysis.json")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 数据处理 ────────────────────────────────────────────────────────

def load_data(account_id: str):
    """加载账号数据"""
    account_dir = DATA_DIR / account_id
    with open(account_dir / "profile.json", "r", encoding="utf-8") as f:
        profile = json.load(f)
    with open(account_dir / "notes.json", "r", encoding="utf-8") as f:
        notes = json.load(f)
    return profile, notes


def parse_timestamp(note_id: str) -> datetime:
    """从 note_id 前8位提取 unix 时间戳"""
    hex_ts = note_id[:8]
    ts = int(hex_ts, 16)
    return datetime.fromtimestamp(ts)


def categorize_note(title: str, topic_keywords: dict) -> str:
    """基于关键词对笔记进行主题分类"""
    for category, keywords in topic_keywords.items():
        for kw in keywords:
            if kw.lower() in title.lower():
                return category
    return "其他"


def match_formulas(title: str, title_formulas: list) -> list:
    """匹配标题使用的公式"""
    matched = []
    for f in title_formulas:
        try:
            if re.search(f["pattern"], title):
                matched.append(f["name"])
        except re.error:
            pass
    return matched


def extract_word_freq(notes: list, cloud_keywords: list) -> list:
    """从标题中提取关键词频次"""
    all_titles = " ".join(n["title"] for n in notes)
    freq = []
    for word in cloud_keywords:
        count = all_titles.lower().count(word.lower())
        if count > 0:
            freq.append((word, count))
    freq.sort(key=lambda x: -x[1])
    return freq[:30]


def process_data(profile: dict, notes: list, analysis: dict) -> dict:
    """处理所有数据，生成看板所需的结构化信息"""
    topic_keywords = analysis["topic_categories"]
    title_formulas = analysis["title_formulas"]
    cloud_keywords = analysis["cloud_keywords"]

    # 时间戳
    for n in notes:
        n["timestamp"] = parse_timestamp(n["note_id"])
        n["date_str"] = n["timestamp"].strftime("%Y-%m-%d")
        n["month_str"] = n["timestamp"].strftime("%Y-%m")
        n["category"] = categorize_note(n["title"], topic_keywords)
        n["formulas"] = match_formulas(n["title"], title_formulas)
        # 封面相对路径
        n["cover_path"] = f"covers/{n['note_id']}.jpg"

    # 按时间排序（旧→新）
    notes.sort(key=lambda x: x["timestamp"])

    # 月度发布统计
    month_counts = Counter(n["month_str"] for n in notes)
    months_sorted = sorted(month_counts.keys())
    monthly_data = [{"month": m, "count": month_counts[m]} for m in months_sorted]

    # 内容类型
    video_count = sum(1 for n in notes if n["type"] == "video")
    image_count = sum(1 for n in notes if n["type"] == "image")

    # 选题分类
    cat_counts = Counter(n["category"] for n in notes)
    topic_data = [
        {"name": k, "count": v}
        for k, v in cat_counts.most_common()
    ]

    # 标题长度分布
    title_lengths = [len(n["title"]) for n in notes]
    len_buckets = {"≤12字": 0, "13-18字": 0, "19-25字": 0, ">25字": 0}
    for tl in title_lengths:
        if tl <= 12:
            len_buckets["≤12字"] += 1
        elif tl <= 18:
            len_buckets["13-18字"] += 1
        elif tl <= 25:
            len_buckets["19-25字"] += 1
        else:
            len_buckets[">25字"] += 1

    # 标题公式统计
    formula_counts = Counter()
    formula_examples = {f["name"]: [] for f in title_formulas}
    for n in notes:
        for fm in n["formulas"]:
            formula_counts[fm] += 1
            if len(formula_examples.get(fm, [])) < 3:
                formula_examples.setdefault(fm, []).append(n["title"])

    formula_data = []
    for f in title_formulas:
        formula_data.append({
            **f,
            "count": formula_counts.get(f["name"], 0),
            "examples": formula_examples.get(f["name"], []),
        })
    formula_data.sort(key=lambda x: -x["count"])

    # 词云数据
    word_freq = extract_word_freq(notes, cloud_keywords)

    # 解析 profile stats
    stats = profile.get("stats_raw", [])
    following = stats[0] if len(stats) > 0 else "0"
    followers = stats[1] if len(stats) > 1 else "0"
    likes_collects = stats[2] if len(stats) > 2 else "0"

    def parse_num(s):
        s = str(s).replace(",", "")
        if "万" in s:
            return float(s.replace("万", "")) * 10000
        try:
            return float(s)
        except ValueError:
            return 0

    try:
        ratio = round(parse_num(likes_collects) / max(parse_num(followers), 1), 1)
    except (ValueError, ZeroDivisionError):
        ratio = 0

    # 真实互动数据汇总（如已爬取）
    notes_with_likes = [n for n in notes if n.get("likes", 0) > 0]
    has_real_likes = len(notes_with_likes) > 0
    total_likes = sum(n.get("likes", 0) for n in notes)
    total_collects = sum(n.get("collects", 0) for n in notes)
    total_comments = sum(n.get("comments", 0) for n in notes)
    avg_likes = round(total_likes / max(len(notes_with_likes), 1))
    avg_video_duration = 0
    video_notes = [n for n in notes if n.get("type") == "video" and n.get("video_duration", 0) > 0]
    if video_notes:
        avg_video_duration = round(sum(n["video_duration"] for n in video_notes) / len(video_notes))

    # 发布频率洞察
    if len(months_sorted) >= 2:
        first_half = months_sorted[: len(months_sorted) // 2]
        second_half = months_sorted[len(months_sorted) // 2 :]
        avg_first = sum(month_counts[m] for m in first_half) / max(len(first_half), 1)
        avg_second = sum(month_counts[m] for m in second_half) / max(len(second_half), 1)
        if avg_second > avg_first * 1.3:
            cadence_insight = f"发布频率从前期的月均 {avg_first:.1f} 篇加速至近期月均 {avg_second:.1f} 篇"
        else:
            cadence_insight = f"月均发布 {sum(month_counts.values()) / max(len(months_sorted), 1):.1f} 篇，节奏稳定"
    else:
        cadence_insight = ""

    # Top 10 笔记（用于 top10 洞察和 TOP10_IDS）
    if has_real_likes:
        top10_notes = sorted(notes, key=lambda x: x.get("likes", 0), reverse=True)[:10]
    else:
        top10_notes = notes[:10]

    top10_note_ids = [n["note_id"][:8] for n in top10_notes]

    # Top 10 笔记公式分析
    top10_formula_counter = Counter()
    for n in top10_notes:
        for fm in n["formulas"]:
            top10_formula_counter[fm] += 1
    if top10_formula_counter:
        parts = []
        for fm_name, fm_cnt in top10_formula_counter.most_common(3):
            parts.append(f"<strong>{fm_name}</strong>（{fm_cnt} 篇）")
        top10_formula_insight = "高互动笔记主要使用：" + "、".join(parts)
    else:
        # fallback：用最多主题 + 内容类型
        top_cat = topic_data[0]["name"] if topic_data else "多元"
        dominant = "视频" if video_count > image_count else "图文"
        top10_formula_insight = f"高互动内容以 <strong>{top_cat}</strong> 为主，{dominant}形式占主导"

    # 选题洞察
    if len(topic_data) >= 2:
        t1, t2 = topic_data[0], topic_data[1]
        combined_pct = round((t1["count"] + t2["count"]) / max(len(notes), 1) * 100)
        topic_insight = f"{t1['name']} + {t2['name']} 占 {combined_pct}%，形成双支柱内容结构"
    elif len(topic_data) == 1:
        t1 = topic_data[0]
        pct = round(t1["count"] / max(len(notes), 1) * 100)
        topic_insight = f"{t1['name']} 占 {pct}%，是账号的核心内容方向"
    else:
        topic_insight = "内容选题多元，尚未形成明显聚焦方向"

    # 标题长度洞察
    best_bucket = max(len_buckets, key=len_buckets.get)
    best_bucket_count = len_buckets[best_bucket]
    best_bucket_pct = round(best_bucket_count / max(len(notes), 1) * 100)
    title_length_insight = f"{best_bucket} 覆盖 {best_bucket_pct}% 的笔记，是该账号标题的主力区间"

    # 封面洞察（仅统计数据，不做视觉判断）
    video_pct = round(video_count / max(len(notes), 1) * 100)
    image_pct = 100 - video_pct
    cover_insight = f"共 {len(notes)} 张封面 · {video_count} 条视频（{video_pct}%）、{image_count} 条图文（{image_pct}%）· Hover 查看详情"

    # 策略：优先使用 analysis.json 中的策略
    strategies = analysis.get("strategies", [])

    # top10 笔记 ID：优先使用 analysis.json
    analysis_top10 = analysis.get("top10_note_ids", [])
    if analysis_top10:
        top10_note_ids = analysis_top10

    # radar_scores from analysis.json
    radar_scores = analysis.get("radar_scores", {})

    return {
        "profile": {
            "nickname": profile.get("nickname", ""),
            "bio": profile.get("bio", ""),
            "xiaohongshu_id": profile.get("xiaohongshu_id", ""),
            "url": profile.get("url", ""),
            "avatar_url": profile.get("avatar_url", ""),
            "ip_location": profile.get("ip_location", ""),
            "following": following,
            "followers": followers,
            "likes_collects": likes_collects,
            "ratio": ratio,
        },
        "has_real_likes": has_real_likes,
        "total_likes": total_likes,
        "total_collects": total_collects,
        "total_comments": total_comments,
        "avg_likes": avg_likes,
        "avg_video_duration": avg_video_duration,
        "notes": [
            {
                "note_id": n["note_id"],
                "title": n["title"],
                "type": n["type"],
                "date_str": n["date_str"],
                "month_str": n["month_str"],
                "category": n["category"],
                "formulas": n["formulas"],
                "likes": n.get("likes", 0),
                "cover_path": n["cover_path"],
                "url": n["url"],
            }
            for n in notes
        ],
        "total_notes": len(notes),
        "video_count": video_count,
        "image_count": image_count,
        "video_pct": round(video_count / max(len(notes), 1) * 100, 1),
        "monthly": monthly_data,
        "topics": topic_data,
        "title_lengths": len_buckets,
        "formulas": formula_data,
        "word_freq": word_freq,
        "cadence_insight": cadence_insight,
        "top10_note_ids": top10_note_ids,
        "top10_formula_insight": top10_formula_insight,
        "topic_insight": topic_insight,
        "title_length_insight": title_length_insight,
        "cover_insight": cover_insight,
        "strategies": strategies,
        "radar_scores": radar_scores,
        "top10_analysis": analysis.get("top10_analysis", []),
        "hit_patterns": analysis.get("hit_patterns", []),
        "title_hit_vs_miss": analysis.get("title_hit_vs_miss", {}),
        "cover_analysis": analysis.get("cover_analysis", {}),
        "category_insights": analysis.get("category_insights", {}),
        "format_comparison": analysis.get("format_comparison", {}),
        "content_formulas_recap": analysis.get("content_formulas_recap", []),
        "action_plan": analysis.get("action_plan", {}),
    }


# ── HTML 生成 ────────────────────────────────────────────────────────

def generate_html(data: dict) -> str:
    p = data["profile"]
    notes_json = json.dumps(data["notes"], ensure_ascii=False)
    monthly_json = json.dumps(data["monthly"], ensure_ascii=False)
    topics_json = json.dumps(data["topics"], ensure_ascii=False)
    formulas_json = json.dumps(data["formulas"], ensure_ascii=False)
    word_freq_json = json.dumps(data["word_freq"], ensure_ascii=False)
    title_lengths_json = json.dumps(data["title_lengths"], ensure_ascii=False)
    top10_ids_json = json.dumps(data["top10_note_ids"], ensure_ascii=False)
    strategies_json = json.dumps(data["strategies"], ensure_ascii=False)
    radar_scores_json = json.dumps(data.get("radar_scores", {}), ensure_ascii=False)
    top10_analysis_json = json.dumps(data.get("top10_analysis", []), ensure_ascii=False)
    hit_patterns_json = json.dumps(data.get("hit_patterns", []), ensure_ascii=False)
    title_hit_vs_miss_json = json.dumps(data.get("title_hit_vs_miss", {}), ensure_ascii=False)
    cover_analysis_json = json.dumps(data.get("cover_analysis", {}), ensure_ascii=False)
    category_insights_json = json.dumps(data.get("category_insights", {}), ensure_ascii=False)
    format_comparison_json = json.dumps(data.get("format_comparison", {}), ensure_ascii=False)
    content_formulas_recap_json = json.dumps(data.get("content_formulas_recap", []), ensure_ascii=False)
    action_plan_json = json.dumps(data.get("action_plan", {}), ensure_ascii=False)

    bio_tags = [
        line.strip().lstrip("▪️").strip()
        for line in p["bio"].split("\n")
        if line.strip()
    ]

    # 头像 HTML
    if p.get("avatar_url"):
        avatar_html = f'<img src="{p["avatar_url"]}" alt="avatar" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">'
    else:
        avatar_html = p["nickname"][0] if p.get("nickname") else "?"

    # IP属地标签
    ip_tag = f'<span class="tag" style="border-color:var(--amber);color:var(--amber);">📍 {p["ip_location"]}</span>' if p.get("ip_location") else ""

    # 互动数据 KPI 已移除（篇均点赞/总收藏/总评论与其他区域重复）

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{p["nickname"]} · 小红书账号分析看板</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&family=Noto+Sans+SC:wght@300;400;500;700;900&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
/* ── Reset & Base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --bg-deep: #f2f3f7;
  --bg-main: #f2f3f7;
  --bg-card: #ffffff;
  --bg-card-hover: #fafbfc;
  --border: transparent;
  --border-hover: rgba(0, 0, 0, 0.06);
  --blue: #3478F6;
  --amber: #F59E0B;
  --red: #EF4444;
  --green: #22C55E;
  --purple: #8B5CF6;
  --orange: #F59E0B;
  --text: #374151;
  --text-dim: #9CA3AF;
  --text-bright: #111827;
  --font-mono: 'SF Mono', 'Menlo', monospace;
  --font-body: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
}}

html {{ scroll-behavior: smooth; }}

body {{
  background: var(--bg-deep);
  color: var(--text);
  font-family: var(--font-body);
  font-weight: 400;
  line-height: 1.7;
  overflow-x: hidden;
}}


/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 6px; }}
::-webkit-scrollbar-track {{ background: #e5e7eb; }}
::-webkit-scrollbar-thumb {{ background: #9CA3AF; border-radius: 3px; }}

/* ── Navigation ── */
.nav {{
  position: sticky; top: 0; z-index: 100;
  display: flex; align-items: center; gap: 8px;
  padding: 12px 32px;
  background: #ffffff;
  border-bottom: 1px solid rgba(0,0,0,0.06);
}}
.nav-brand {{
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-bright);
  letter-spacing: 2px;
  text-transform: uppercase;
  margin-right: auto;
}}
.nav a {{
  color: var(--text-dim);
  text-decoration: none;
  font-size: 13px;
  padding: 4px 12px;
  border-radius: 4px;
  transition: all 0.2s;
}}
.nav a:hover {{ color: var(--blue); background: rgba(52,120,246,0.06); }}

/* ── Layout ── */
.container {{ max-width: 1400px; margin: 0 auto; padding: 0 32px; }}
section {{ padding: 64px 0; }}

/* ── Section Titles ── */
.section-tag {{
  font-family: var(--font-body);
  font-size: 11px;
  color: var(--blue);
  letter-spacing: 3px;
  text-transform: uppercase;
  margin-bottom: 8px;
  opacity: 0.7;
}}
.section-title {{
  font-family: var(--font-body);
  font-weight: 900;
  font-size: 28px;
  color: var(--text-bright);
  margin-bottom: 8px;
}}
.section-subtitle {{
  font-size: 14px;
  color: var(--text-dim);
  margin-bottom: 40px;
}}

/* ── Cards ── */
.card {{
  background: #ffffff;
  border: none;
  border-radius: 20px;
  padding: 28px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.03);
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}}
.card:hover {{
  box-shadow: 0 2px 8px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.06);
}}

/* ── Insight Callouts ── */
.insight {{
  display: flex; align-items: flex-start; gap: 12px;
  padding: 16px 20px;
  background: #EFF6FF;
  border-left: 3px solid var(--blue);
  border-radius: 0 12px 12px 0;
  margin: 24px 0;
  font-size: 14px;
  color: var(--text-bright);
}}

/* ── Animations ── */
@keyframes fadeUp {{
  from {{ opacity: 0; transform: translateY(30px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes pulse {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0.5; }}
}}
.animate-in {{
  opacity: 0;
  transform: translateY(30px);
  transition: all 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}}
.animate-in.visible {{
  opacity: 1;
  transform: translateY(0);
}}

/* ══════════════════════════════════════════════════
   SECTION 1: HERO
   ══════════════════════════════════════════════════ */
.hero {{
  position: relative;
  padding: 80px 0 60px;
  overflow: hidden;
}}

.hero-header {{
  display: flex;
  align-items: center;
  gap: 24px;
  margin-bottom: 40px;
  position: relative;
}}
.hero-avatar {{
  width: 72px; height: 72px;
  border-radius: 50%;
  background: var(--blue);
  display: flex; align-items: center; justify-content: center;
  font-family: var(--font-body);
  font-size: 24px;
  font-weight: 900;
  color: #ffffff;
  flex-shrink: 0;
}}
.hero-info h1 {{
  font-family: var(--font-body);
  font-weight: 900;
  font-size: 32px;
  color: var(--text-bright);
  margin-bottom: 4px;
}}
.hero-info .xhs-id {{
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-dim);
}}
.hero-tags {{
  display: flex; flex-wrap: wrap; gap: 8px;
  margin-bottom: 40px;
}}
.hero-tags .tag {{
  padding: 4px 14px;
  border-radius: 100px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--border);
  color: var(--text-dim);
  background: rgba(0,0,0,0.02);
}}
.hero-tags .tag:first-child {{
  border-color: var(--blue);
  color: var(--blue);
  background: rgba(52,120,246,0.06);
}}

/* KPI Grid */
.kpi-grid {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}}
.kpi {{
  text-align: center;
  padding: 32px 20px;
}}
.kpi-value {{
  font-family: var(--font-body);
  font-size: 36px;
  font-weight: 900;
  color: var(--text-bright);
  line-height: 1.2;
  margin-bottom: 8px;
}}
.kpi-label {{
  font-size: 13px;
  color: var(--text-dim);
  letter-spacing: 1px;
}}
.kpi-sub {{
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--green);
  margin-top: 6px;
}}

/* Meta bar */
.meta-bar {{
  display: flex; gap: 24px;
  padding: 16px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  font-size: 13px;
  color: var(--text-dim);
}}
.meta-bar span {{ display: flex; align-items: center; gap: 6px; }}
.meta-bar .dot {{
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
}}
.meta-bar .dot-video {{ background: var(--blue); }}
.meta-bar .dot-image {{ background: var(--amber); }}
.meta-bar .dot-stage {{ background: var(--green); animation: pulse 2s infinite; }}

/* ══════════════════════════════════════════════════
   SECTION 2: TIMELINE
   ══════════════════════════════════════════════════ */
.timeline-chart-wrap {{
  position: relative;
  height: 300px;
  padding: 20px;
}}

/* ══════════════════════════════════════════════════
   SECTION 3: TOPICS
   ══════════════════════════════════════════════════ */
.topics-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-bottom: 24px;
}}
.chart-wrap {{
  height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}}
.topic-notes {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.5s ease;
}}
.topic-notes.open {{
  max-height: 2000px;
}}
.topic-note-card {{
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 13px;
  cursor: pointer;
  text-decoration: none;
  color: var(--text);
  transition: all 0.2s;
}}
.topic-note-card:hover {{
  border-color: var(--border-hover);
  background: var(--bg-card-hover);
}}
.topic-note-card img {{
  width: 48px; height: 48px;
  object-fit: cover;
  border-radius: 6px;
  flex-shrink: 0;
}}
.topic-filter-bar {{
  display: flex; flex-wrap: wrap; gap: 8px;
  margin-bottom: 16px;
}}
.topic-filter {{
  padding: 6px 16px;
  border-radius: 100px;
  font-size: 12px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.2s;
  font-family: var(--font-body);
}}
.topic-filter:hover, .topic-filter.active {{
  border-color: var(--blue);
  color: var(--blue);
  background: rgba(0,212,255,0.08);
}}

/* ══════════════════════════════════════════════════
   SECTION 4: TITLE FORMULAS
   ══════════════════════════════════════════════════ */
.formulas-grid {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 32px;
}}
.formula-card {{
  padding: 24px;
  position: relative;
  overflow: hidden;
}}
.formula-card::before {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  border-radius: 16px 16px 0 0;
}}
.formula-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}}
.formula-name {{
  font-weight: 700;
  font-size: 16px;
  color: var(--text-bright);
}}
.formula-badge {{
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 100px;
  background: rgba(0,0,0,0.04);
  color: var(--text-dim);
}}
.formula-template {{
  font-family: var(--font-mono);
  font-size: 13px;
  padding: 10px 14px;
  background: rgba(0,0,0,0.03);
  border-radius: 8px;
  margin-bottom: 14px;
  border-left: 2px solid;
}}
.formula-trigger {{
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 12px;
  padding: 6px 10px;
  background: rgba(52,120,246,0.04);
  border-radius: 6px;
}}
.formula-examples {{
  list-style: none;
  font-size: 12px;
  color: var(--text-dim);
}}
.formula-examples li {{
  padding: 4px 0;
  border-bottom: 1px solid rgba(0,0,0,0.04);
}}
.formula-examples li::before {{
  content: '→ ';
  color: var(--blue);
}}

/* Title Length Chart */
.title-length-wrap {{
  display: grid;
  grid-template-columns: 2fr 3fr;
  gap: 24px;
}}
.title-length-chart {{ height: 220px; padding: 16px; }}

/* Word Cloud */
.word-cloud {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px 14px;
  padding: 32px;
  min-height: 200px;
}}
.cloud-word {{
  font-family: var(--font-body);
  font-weight: 700;
  transition: all 0.3s;
  cursor: default;
  opacity: 0.85;
}}
.cloud-word:hover {{
  opacity: 1;
  text-shadow: 0 0 20px currentColor;
  transform: scale(1.1);
}}

/* ══════════════════════════════════════════════════
   SECTION 5: COVERS
   ══════════════════════════════════════════════════ */
.cover-wall {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}}
.cover-item {{
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  aspect-ratio: 3/4;
  cursor: pointer;
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid var(--border);
}}
.cover-item:hover {{
  transform: scale(1.04);
  border-color: var(--blue);
  box-shadow: 0 8px 40px rgba(0,0,0,0.12);
  z-index: 10;
}}
.cover-item img {{
  width: 100%; height: 100%;
  object-fit: cover;
  transition: transform 0.4s;
}}
.cover-item:hover img {{
  transform: scale(1.08);
}}
.cover-overlay {{
  position: absolute;
  inset: 0;
  background: linear-gradient(transparent 40%, rgba(0,0,0,0.75));
  display: flex;
  align-items: flex-end;
  padding: 14px;
  opacity: 0;
  transition: opacity 0.3s;
}}
.cover-item:hover .cover-overlay {{
  opacity: 1;
}}
.cover-overlay-text {{
  font-size: 12px;
  font-weight: 500;
  color: var(--text-bright);
  line-height: 1.5;
}}
.cover-overlay-meta {{
  font-size: 10px;
  color: var(--text-dim);
  margin-top: 4px;
  font-family: var(--font-mono);
}}
.cover-type-badge {{
  position: absolute;
  top: 8px; right: 8px;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: var(--font-mono);
  background: rgba(0,0,0,0.5);
  backdrop-filter: blur(4px);
}}
.cover-type-badge.video {{ color: var(--blue); border: 1px solid rgba(52,120,246,0.3); }}
.cover-type-badge.image {{ color: var(--amber); border: 1px solid rgba(245,158,11,0.3); }}

/* ══════════════════════════════════════════════════
   SECTION 6: TOP 10
   ══════════════════════════════════════════════════ */
.top-list {{
  display: flex;
  flex-direction: column;
  gap: 12px;
}}
.top-item {{
  display: grid;
  grid-template-columns: 40px 72px 1fr auto;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
}}
.top-rank {{
  font-family: var(--font-body);
  font-size: 20px;
  font-weight: 900;
  text-align: center;
}}
.top-rank.gold {{ color: var(--amber); }}
.top-rank.silver {{ color: #c0c0c0; }}
.top-rank.bronze {{ color: #cd7f32; }}
.top-item img {{
  width: 72px; height: 54px;
  object-fit: cover;
  border-radius: 8px;
}}
.top-title {{
  font-size: 14px;
  font-weight: 500;
  color: var(--text-bright);
}}
.top-tags {{
  display: flex; gap: 6px; flex-wrap: wrap;
  margin-top: 4px;
}}
.top-tags span {{
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: var(--font-mono);
}}

/* ══════════════════════════════════════════════════
   SECTION 7: METHODOLOGY
   ══════════════════════════════════════════════════ */
.strategy-list {{
  display: flex;
  flex-direction: column;
  gap: 16px;
}}
.strategy-item {{
  padding: 24px 28px;
  border-left: 4px solid var(--blue);
  background: var(--bg-card);
  border-radius: 16px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}}
.strategy-header {{
  display: flex;
  align-items: center;
  gap: 14px;
}}
.strategy-num {{
  font-family: var(--font-body);
  font-size: 16px;
  font-weight: 700;
  color: #ffffff;
  background: linear-gradient(135deg, #3478F6, #2563EB);
  width: 40px; height: 40px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 12px;
  flex-shrink: 0;
}}
.strategy-title {{
  font-weight: 700;
  font-size: 17px;
  color: var(--text-bright);
  flex: 1;
}}
.strategy-body {{
  padding-left: 54px;
}}
.strategy-body p {{
  padding-top: 14px;
  font-size: 14px;
  color: var(--text);
  line-height: 1.8;
}}
.strategy-action {{
  margin-top: 12px;
  padding: 12px 16px;
  background: rgba(52,120,246,0.08);
  border-left: 3px solid var(--blue);
  border-radius: 8px;
  font-size: 13px;
  color: var(--blue);
  font-weight: 500;
}}

/* ── Footer ── */
.footer {{
  text-align: center;
  padding: 40px 0;
  font-size: 12px;
  color: var(--text-dim);
  border-top: 1px solid var(--border);
}}

/* ── Responsive ── */
@media (max-width: 900px) {{
  .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .topics-grid {{ grid-template-columns: 1fr; }}
  .formulas-grid {{ grid-template-columns: 1fr; }}
  .title-length-wrap {{ grid-template-columns: 1fr; }}
  .cover-wall {{ grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }}
  .top-item {{ grid-template-columns: 30px 1fr; }}
  .top-item img {{ display: none; }}
}}
/* ── Success Factors (Top 10) ── */
.success-factors {{
  font-size: 12px;
  color: var(--text-dim);
  margin-top: 4px;
  padding-left: 4px;
  border-left: 2px solid rgba(0,212,255,0.2);
  line-height: 1.5;
}}

/* ── Hit Patterns Callout ── */
.hit-patterns {{
  background: #FFFBEB;
  border: 1px solid rgba(245,158,11,0.15);
  border-radius: 12px;
  padding: 20px 24px;
  margin-top: 24px;
}}
.hit-patterns h4 {{
  color: var(--amber);
  font-size: 14px;
  margin-bottom: 12px;
  font-weight: 700;
}}
.hit-patterns li {{
  color: var(--text);
  font-size: 13px;
  margin-bottom: 6px;
  list-style: none;
  padding-left: 16px;
  position: relative;
}}
.hit-patterns li::before {{
  content: '⚡';
  position: absolute;
  left: 0;
}}

/* ── Cover Style Grid ── */
.cover-styles-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  margin: 24px 0;
}}
.cover-style-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}}
.cover-style-card h4 {{
  font-size: 15px;
  color: var(--text-bright);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}}
.cover-style-card .count-badge {{
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 100px;
  background: rgba(0,212,255,0.1);
  color: var(--blue);
}}
.perf-badge {{
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 100px;
  text-transform: uppercase;
  letter-spacing: 1px;
}}
.perf-high {{ background: rgba(34,197,94,0.1); color: var(--green); }}
.perf-medium {{ background: rgba(245,158,11,0.1); color: var(--amber); }}
.perf-mixed {{ background: rgba(139,92,246,0.1); color: var(--purple); }}
.perf-low {{ background: rgba(239,68,68,0.1); color: var(--red); }}

/* ── Template Suggestion ── */
.template-block {{
  background: #f3f4f6;
  border: 1px solid rgba(0,0,0,0.06);
  border-radius: 12px;
  padding: 20px 24px;
  margin: 24px 0;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-bright);
  line-height: 1.8;
  white-space: pre-wrap;
}}
.template-block .label {{
  font-family: var(--font-body);
  font-size: 12px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 2px;
  margin-bottom: 8px;
  display: block;
}}

/* ── Category Insight Cards ── */
.category-insights-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  margin-top: 24px;
}}
.cat-insight-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}}
.cat-insight-card h4 {{
  font-size: 14px;
  color: var(--text-bright);
  margin-bottom: 8px;
}}
.cat-insight-card p {{
  font-size: 13px;
  color: var(--text-dim);
  line-height: 1.7;
}}

/* ── Format Comparison ── */
.format-kpi-row {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}}
.format-kpi {{
  text-align: center;
  padding: 32px 20px;
}}
.format-kpi .big-num {{
  font-family: var(--font-body);
  font-size: 48px;
  font-weight: 900;
  line-height: 1.1;
  margin-bottom: 8px;
}}
.format-kpi .sub {{
  font-size: 13px;
  color: var(--text-dim);
}}
.format-table {{
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  margin-top: 16px;
}}
.format-table th {{
  text-align: left;
  padding: 10px 16px;
  font-size: 11px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 1px;
  border-bottom: 1px solid var(--border);
}}
.format-table td {{
  padding: 12px 16px;
  font-size: 13px;
  color: var(--text);
  border-bottom: 1px solid rgba(0,0,0,0.04);
}}
.format-table tr:last-child td {{ border-bottom: none; }}

/* ── Hit vs Miss Table ── */
.hvm-table {{
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  margin: 24px 0;
}}
.hvm-table th {{
  padding: 12px 16px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1px;
}}
.hvm-table th.dim {{ color: var(--text-dim); text-align: left; width: 20%; }}
.hvm-table th.hit {{ color: var(--green); text-align: center; }}
.hvm-table th.miss {{ color: var(--red); text-align: center; opacity: 0.6; }}
.hvm-table td {{
  padding: 12px 16px;
  font-size: 13px;
  border-bottom: 1px solid rgba(0,0,0,0.04);
}}
.hvm-table td.dim-cell {{ color: var(--text-bright); font-weight: 500; }}
.hvm-table td.hit-cell {{ color: var(--green); text-align: center; background: rgba(34,197,94,0.04); }}
.hvm-table td.miss-cell {{ color: var(--text-dim); text-align: center; background: rgba(239,68,68,0.04); }}

/* ── Content Formulas Recap ── */
.formulas-recap-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  margin: 24px 0;
}}
.formula-recap-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
}}
.formula-recap-card .recap-label {{
  font-size: 13px;
  font-weight: 700;
  color: var(--blue);
  margin-bottom: 8px;
}}
.formula-recap-card .recap-template {{
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  background: rgba(0,0,0,0.04);
  padding: 8px 12px;
  border-radius: 6px;
  line-height: 1.6;
}}

/* ── Action Plan ── */
.action-plan-grid {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}}
.action-col {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 0;
  overflow: hidden;
}}
.action-col h4 {{
  font-size: 15px;
  font-weight: 700;
  margin: 0;
  padding: 16px 24px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ffffff;
}}
.action-col.week {{ background: rgba(34,197,94,0.03); }}
.action-col.month {{ background: rgba(245,158,11,0.03); }}
.action-col.long {{ background: rgba(139,92,246,0.03); }}
.action-col.week h4 {{ background: linear-gradient(135deg, #22C55E, #16A34A); }}
.action-col.month h4 {{ background: linear-gradient(135deg, #F59E0B, #D97706); }}
.action-col.long h4 {{ background: linear-gradient(135deg, #8B5CF6, #7C3AED); }}
.action-col ul {{ list-style: none; padding: 20px 24px; }}
.action-col li {{
  font-size: 14px;
  color: var(--text);
  padding: 12px 0;
  border-bottom: 1px solid rgba(0,0,0,0.04);
  display: flex;
  align-items: flex-start;
  gap: 10px;
}}
.action-col li:last-child {{ border-bottom: none; }}
.action-col li::before {{
  content: '';
  width: 16px; height: 16px;
  border: 2px solid var(--border-hover);
  border-radius: 4px;
  flex-shrink: 0;
  margin-top: 2px;
}}
.action-col.week li::before {{ border-color: var(--green); }}
.action-col.month li::before {{ border-color: var(--amber); }}
.action-col.long li::before {{ border-color: var(--purple); }}

/* ── Numbered List ── */
.numbered-list {{
  counter-reset: item;
  list-style: none;
  margin: 16px 0;
}}
.numbered-list li {{
  counter-increment: item;
  padding: 8px 0 8px 32px;
  position: relative;
  font-size: 13px;
  color: var(--text);
}}
.numbered-list li::before {{
  content: counter(item);
  position: absolute;
  left: 0;
  width: 22px; height: 22px;
  background: rgba(0,212,255,0.1);
  color: var(--blue);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono);
}}

@media (max-width: 768px) {{
  .action-plan-grid {{ grid-template-columns: 1fr; }}
  .format-kpi-row {{ grid-template-columns: 1fr; }}
  .hvm-table {{ font-size: 11px; }}
}}
</style>
</head>
<body>

<!-- ── Navigation ── -->
<nav class="nav">
  <div class="nav-brand">XHS ANALYZER</div>
  <a href="#hero">概览</a>
  <a href="#timeline">时间线</a>
  <a href="#topics">选题</a>
  <a href="#titles">标题</a>
  <a href="#covers">封面</a>
  <a href="#top10">爆款</a>
  <a href="#format">形式</a>
  <a href="#strategy">方法论</a>
  <a href="#action">行动</a>
</nav>

<!-- ══ SECTION 1: HERO ══ -->
<section class="hero" id="hero">
  <div class="container">
    <div class="hero-header animate-in">
      <div class="hero-avatar">{avatar_html}</div>
      <div class="hero-info">
        <h1>{p["nickname"]}</h1>
        <span class="xhs-id">ID: {p["xiaohongshu_id"]}</span>
      </div>
    </div>

    <div class="hero-tags animate-in">
      {"".join(f'<span class="tag">{t}</span>' for t in bio_tags)}
      {ip_tag}
    </div>

    <div class="kpi-grid">
      <div class="card kpi animate-in">
        <div class="kpi-value">{p["followers"]}</div>
        <div class="kpi-label">粉丝</div>
      </div>
      <div class="card kpi animate-in">
        <div class="kpi-value">{p["following"]}</div>
        <div class="kpi-label">关注</div>
      </div>
      <div class="card kpi animate-in">
        <div class="kpi-value">{p["likes_collects"]}</div>
        <div class="kpi-label">获赞与收藏</div>
      </div>
      <div class="card kpi animate-in">
        <div class="kpi-value">{p["ratio"]}x</div>
        <div class="kpi-label">粉均赞藏比</div>
        <div class="kpi-sub">{"▲ 高于平均" if p["ratio"] > 3 else ""}</div>
      </div>
    </div>

    <div class="meta-bar animate-in">
      <span>共 <strong>{data["total_notes"]}</strong> 篇笔记</span>
      <span><span class="dot dot-video"></span>视频 {data["video_count"]} 篇（{data["video_pct"]}%）</span>
      <span><span class="dot dot-image"></span>图文 {data["image_count"]} 篇</span>
      <span><span class="dot dot-stage"></span>成长期</span>
    </div>
  </div>
</section>

<!-- ══ SECTION 2: TIMELINE ══ -->
<section id="timeline">
  <div class="container">
    <div class="section-tag animate-in">TIMELINE</div>
    <div class="section-title animate-in">发布节奏</div>
    <div class="section-subtitle animate-in">基于笔记ID时间戳反向推算</div>

    <div class="card timeline-chart-wrap animate-in">
      <canvas id="timelineChart"></canvas>
    </div>

    {f'<div class="insight animate-in">{data["cadence_insight"]}</div>' if data["cadence_insight"] else ""}
  </div>
</section>

<!-- ══ SECTION 3: TOPICS ══ -->
<section id="topics">
  <div class="container">
    <div class="section-tag animate-in">TOPICS</div>
    <div class="section-title animate-in">选题分布</div>
    <div class="section-subtitle animate-in">基于标题关键词自动分类</div>

    <div class="topics-grid">
      <div class="card animate-in">
        <div class="chart-wrap">
          <canvas id="topicDonut"></canvas>
        </div>
      </div>
      <div class="card animate-in">
        <div class="chart-wrap">
          <canvas id="topicRadar"></canvas>
        </div>
      </div>
    </div>

    <div class="card animate-in" style="margin-top:20px;">
      <h3 style="font-size:15px;color:var(--text-bright);margin-bottom:16px;">各类别篇均点赞</h3>
      <div style="height:200px;">
        <canvas id="topicLikesChart"></canvas>
      </div>
    </div>

    <div class="insight animate-in">
      {data["topic_insight"]}
    </div>

    <div class="category-insights-grid animate-in" id="categoryInsights"></div>

    <div class="topic-filter-bar animate-in" id="topicFilterBar"></div>
    <div class="topic-notes" id="topicNotes"></div>
  </div>
</section>

<!-- ══ SECTION 3.5: FORMAT COMPARISON ══ -->
<section id="format">
  <div class="container">
    <div class="section-tag animate-in">FORMAT ANALYSIS</div>
    <div class="section-title animate-in">内容形式对比</div>
    <div class="section-subtitle animate-in">视频 vs 图文表现分析</div>

    <div class="format-kpi-row">
      <div class="card format-kpi animate-in">
        <div class="big-num" style="color:var(--text-bright);" id="fmtVideoLikes"></div>
        <div class="sub">视频篇均点赞</div>
      </div>
      <div class="card format-kpi animate-in">
        <div class="big-num" style="color:var(--text-bright);" id="fmtImageLikes"></div>
        <div class="sub">图文篇均点赞</div>
      </div>
    </div>

    <div class="insight animate-in" id="fmtInsight"></div>

    <div class="card animate-in" style="margin-top:24px;">
      <h3 style="font-size:15px;color:var(--text-bright);margin-bottom:16px;">各类别最佳形式</h3>
      <table class="format-table" id="fmtTable">
        <thead><tr><th>类别</th><th>推荐形式</th><th>原因</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</section>

<!-- ══ SECTION 4: TITLE FORMULAS ══ -->
<section id="titles">
  <div class="container">
    <div class="section-tag animate-in">TITLE FORMULAS</div>
    <div class="section-title animate-in">标题方法论</div>
    <div class="section-subtitle animate-in">6 大高频标题公式拆解</div>

    <div class="formulas-grid" id="formulasGrid"></div>

    <div class="title-length-wrap">
      <div class="card animate-in">
        <h3 style="font-size:15px;color:var(--text-bright);margin-bottom:16px;">标题长度分布</h3>
        <div class="title-length-chart">
          <canvas id="titleLenChart"></canvas>
        </div>
        <div class="insight" style="margin-top:16px;">
          {data["title_length_insight"]}
        </div>
      </div>
      <div class="card animate-in">
        <h3 style="font-size:15px;color:var(--text-bright);margin-bottom:16px;">标题高频词</h3>
        <div class="word-cloud" id="wordCloud"></div>
      </div>
    </div>

    <div class="card animate-in" style="margin-top:24px;" id="hvmWrap">
      <h3 style="font-size:15px;color:var(--text-bright);margin-bottom:16px;">爆款 vs 普通标题对比</h3>
      <table class="hvm-table" id="hvmTable">
        <thead><tr><th class="dim">维度</th><th class="hit">爆款特征</th><th class="miss">普通特征</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</section>

<!-- ══ SECTION 5: COVERS ══ -->
<section id="covers">
  <div class="container">
    <div class="section-tag animate-in">COVER DESIGN</div>
    <div class="section-title animate-in">封面视觉系统</div>
    <div class="section-subtitle animate-in">全部 {data["total_notes"]} 张封面 · Hover 查看详情</div>

    <div class="insight animate-in">
      {data["cover_insight"]}
    </div>

    <div class="cover-wall animate-in" id="coverWall"></div>

    <div class="cover-styles-grid animate-in" id="coverStyles"></div>

    <div class="card animate-in" style="margin-top:24px;" id="coverPatternsWrap">
      <h3 style="font-size:15px;color:var(--text-bright);margin-bottom:12px;">爆款封面共性</h3>
      <ol class="numbered-list" id="coverPatterns"></ol>
    </div>

    <div class="template-block animate-in" id="coverTemplate">
      <span class="label">推荐封面模板</span>
      <span id="coverTemplateText"></span>
    </div>
  </div>
</section>

<!-- ══ SECTION 6: TOP 10 ══ -->
<section id="top10">
  <div class="container">
    <div class="section-tag animate-in">TOP CONTENT</div>
    <div class="section-title animate-in">{"真实互动排行 Top 10" if data.get("has_real_likes") else "推测高互动笔记 Top 10"}</div>
    <div class="section-subtitle animate-in">{"按实际点赞数降序排列" if data.get("has_real_likes") else "基于标题特征与封面设计质量综合判断"}</div>

    <div class="top-list" id="topList"></div>

    <div class="hit-patterns animate-in" id="hitPatterns"></div>

    <div class="insight animate-in">
      {data["top10_formula_insight"]}
    </div>
  </div>
</section>

<!-- ══ SECTION 7: METHODOLOGY ══ -->
<section id="strategy">
  <div class="container">
    <div class="section-tag animate-in">METHODOLOGY</div>
    <div class="section-title animate-in">可复制的方法论</div>
    <div class="section-subtitle animate-in">5 条核心增长策略</div>

    <div class="formulas-recap-grid animate-in" id="formulasRecap"></div>

    <div class="strategy-list" id="strategyList"></div>
  </div>
</section>

<!-- ══ SECTION 8: ACTION PLAN ══ -->
<section id="action">
  <div class="container">
    <div class="section-tag animate-in">ACTION PLAN</div>
    <div class="section-title animate-in">行动计划</div>
    <div class="section-subtitle animate-in">可执行的分阶段 To-Do List</div>

    <div class="action-plan-grid animate-in" id="actionPlan"></div>
  </div>
</section>

<footer class="footer">
  <div class="container">
    小红书账号分析看板 · 数据来源：主页卡片抓取 · 生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}
  </div>
</footer>

<!-- ══ SCRIPTS ══ -->
<script>
// ── DATA ──
const NOTES = {notes_json};
const MONTHLY = {monthly_json};
const TOPICS = {topics_json};
const FORMULAS = {formulas_json};
const WORD_FREQ = {word_freq_json};
const TITLE_LENGTHS = {title_lengths_json};

// ── Top 10 predicted high-engagement ──
const TOP10_IDS = {top10_ids_json};

// ── Strategies ──
const STRATEGIES = {strategies_json};

// ── New analysis data ──
const TOP10_ANALYSIS = {top10_analysis_json};
const HIT_PATTERNS = {hit_patterns_json};
const TITLE_HIT_VS_MISS = {title_hit_vs_miss_json};
const COVER_ANALYSIS = {cover_analysis_json};
const CATEGORY_INSIGHTS = {category_insights_json};
const FORMAT_COMPARISON = {format_comparison_json};
const CONTENT_FORMULAS_RECAP = {content_formulas_recap_json};
const ACTION_PLAN = {action_plan_json};

// ── Chart.js Global Config ──
Chart.defaults.color = '#6B7280';
Chart.defaults.borderColor = 'rgba(0,0,0,0.04)';
Chart.defaults.font.family = "'Inter', 'Noto Sans SC', sans-serif";
Chart.defaults.font.size = 12;

// ── Timeline Chart ──
new Chart(document.getElementById('timelineChart'), {{
  type: 'bar',
  data: {{
    labels: MONTHLY.map(m => m.month),
    datasets: [{{
      label: '发布数量',
      data: MONTHLY.map(m => m.count),
      backgroundColor: MONTHLY.map((m, i) =>
        `rgba(52, 120, 246, ${{0.3 + (i / MONTHLY.length) * 0.5}})`
      ),
      borderColor: '#3478F6',
      borderWidth: 1,
      borderRadius: 6,
      barPercentage: 0.7,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#ffffff',
        borderColor: 'rgba(0,0,0,0.08)',
        borderWidth: 1,
        titleFont: {{ weight: '700' }},
        callbacks: {{
          label: ctx => `${{ctx.parsed.y}} 篇笔记`
        }}
      }}
    }},
    scales: {{
      x: {{
        grid: {{ display: false }},
        ticks: {{ maxRotation: 45 }}
      }},
      y: {{
        beginAtZero: true,
        ticks: {{ stepSize: 1 }},
        grid: {{ color: 'rgba(0,0,0,0.04)' }}
      }}
    }}
  }}
}});

// ── Topic Donut ──
const topicColors = ['#3478F6', '#F59E0B', '#EF4444', '#22C55E', '#8B5CF6', '#9CA3AF'];
new Chart(document.getElementById('topicDonut'), {{
  type: 'doughnut',
  data: {{
    labels: TOPICS.map(t => t.name),
    datasets: [{{
      data: TOPICS.map(t => t.count),
      backgroundColor: topicColors.slice(0, TOPICS.length),
      borderColor: '#ffffff',
      borderWidth: 3,
      hoverOffset: 8,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    cutout: '60%',
    plugins: {{
      legend: {{
        position: 'bottom',
        labels: {{ padding: 16, usePointStyle: true, pointStyle: 'circle' }}
      }}
    }}
  }}
}});

// ── Topic Radar ──
const radarLabels = ['收藏潜力', '分享潜力', '时效性', '专业门槛', '变现潜力'];
const radarDataMap = {radar_scores_json};
const radarDatasets = TOPICS.slice(0, 5).map((t, i) => ({{
  label: t.name,
  data: radarDataMap[t.name] || [50,50,50,50,50],
  borderColor: topicColors[i],
  backgroundColor: topicColors[i] + '15',
  borderWidth: 2,
  pointRadius: 3,
  pointBackgroundColor: topicColors[i],
}}));
new Chart(document.getElementById('topicRadar'), {{
  type: 'radar',
  data: {{ labels: radarLabels, datasets: radarDatasets }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      r: {{
        beginAtZero: true,
        max: 100,
        ticks: {{ display: false, stepSize: 20 }},
        grid: {{ color: 'rgba(0,0,0,0.06)' }},
        angleLines: {{ color: 'rgba(0,0,0,0.06)' }},
        pointLabels: {{ font: {{ size: 11 }} }}
      }}
    }},
    plugins: {{
      legend: {{
        position: 'bottom',
        labels: {{ padding: 12, usePointStyle: true, pointStyle: 'circle', font: {{ size: 10 }} }}
      }}
    }}
  }}
}});

// ── Topic Likes Bar Chart ──
(function() {{
  const canvas = document.getElementById('topicLikesChart');
  if (!canvas) return;
  const catLikes = {{}};
  NOTES.forEach(n => {{
    const cat = n.category || '其他';
    if (!catLikes[cat]) catLikes[cat] = {{sum: 0, count: 0}};
    catLikes[cat].sum += n.likes || 0;
    catLikes[cat].count++;
  }});
  const cats = Object.keys(catLikes);
  const avgs = cats.map(c => Math.round(catLikes[c].sum / catLikes[c].count));
  const barColors = ['#3478F6', '#F59E0B', '#EF4444', '#22C55E', '#8B5CF6', '#9CA3AF'];
  new Chart(canvas, {{
    type: 'bar',
    data: {{
      labels: cats,
      datasets: [{{
        data: avgs,
        backgroundColor: cats.map((_, i) => barColors[i % barColors.length] + '33'),
        borderColor: cats.map((_, i) => barColors[i % barColors.length]),
        borderWidth: 1,
        borderRadius: 8,
      }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: ctx => `篇均 ${{ctx.parsed.x}} 赞` }} }}
      }},
      scales: {{
        x: {{ grid: {{ color: 'rgba(0,0,0,0.04)' }}, ticks: {{ stepSize: 50 }} }},
        y: {{ grid: {{ display: false }} }}
      }}
    }}
  }});
}})();

// ── Topic Filter ──
(function() {{
  const bar = document.getElementById('topicFilterBar');
  const box = document.getElementById('topicNotes');
  const cats = TOPICS.map(t => t.name);

  cats.forEach(cat => {{
    const btn = document.createElement('button');
    btn.className = 'topic-filter';
    btn.textContent = cat;
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.topic-filter').forEach(b => b.classList.remove('active'));
      if (box.classList.contains('open') && box.dataset.cat === cat) {{
        box.classList.remove('open');
        return;
      }}
      btn.classList.add('active');
      box.dataset.cat = cat;
      box.innerHTML = '';
      NOTES.filter(n => n.category === cat).forEach(n => {{
        const a = document.createElement('a');
        a.className = 'topic-note-card';
        a.href = n.url;
        a.target = '_blank';
        a.innerHTML = `<img src="${{n.cover_path}}" alt="" loading="lazy"><span>${{n.title}}</span>`;
        box.appendChild(a);
      }});
      box.classList.add('open');
    }});
    bar.appendChild(btn);
  }});
}})();

// ── Formula Cards ──
(function() {{
  // Compute avg likes per formula
  const formulaLikes = {{}};
  FORMULAS.forEach(f => {{ formulaLikes[f.name] = {{sum: 0, count: 0}}; }});
  NOTES.forEach(n => {{
    if (n.formulas) {{
      n.formulas.forEach(fname => {{
        if (formulaLikes[fname]) {{
          formulaLikes[fname].sum += n.likes || 0;
          formulaLikes[fname].count++;
        }}
      }});
    }}
  }});

  const grid = document.getElementById('formulasGrid');
  FORMULAS.forEach(f => {{
    const fl = formulaLikes[f.name];
    const avgLikes = fl && fl.count > 0 ? Math.round(fl.sum / fl.count) : null;
    const likesBadge = avgLikes !== null ? `<span class="formula-badge" style="background:rgba(239,68,68,0.08);color:#EF4444;">♥ 均 ${{avgLikes}}</span>` : '';
    const div = document.createElement('div');
    div.className = 'card formula-card animate-in';
    div.innerHTML = `
      <div style="position:absolute;top:0;left:0;right:0;height:3px;background:${{f.color}};border-radius:16px 16px 0 0;"></div>
      <div class="formula-header">
        <span class="formula-name" style="color:${{f.color}}">${{f.name}}</span>
        <span class="formula-badge">${{f.count}} 次</span>
        ${{likesBadge}}
      </div>
      <div class="formula-template" style="border-color:${{f.color}}">${{f.template}}</div>
      <div class="formula-trigger">🧠 ${{f.trigger}}</div>
      <ul class="formula-examples">
        ${{f.examples.map(e => `<li>${{e}}</li>`).join('')}}
      </ul>
    `;
    grid.appendChild(div);
  }});
}})();

// ── Title Length Chart ──
new Chart(document.getElementById('titleLenChart'), {{
  type: 'bar',
  data: {{
    labels: Object.keys(TITLE_LENGTHS),
    datasets: [{{
      data: Object.values(TITLE_LENGTHS),
      backgroundColor: ['rgba(52,120,246,0.2)', 'rgba(245,158,11,0.2)', 'rgba(34,197,94,0.2)', 'rgba(139,92,246,0.2)'],
      borderColor: ['#3478F6', '#F59E0B', '#22C55E', '#8B5CF6'],
      borderWidth: 1,
      borderRadius: 8,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{ label: ctx => `${{ctx.parsed.x}} 篇` }}
      }}
    }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.04)' }}, ticks: {{ stepSize: 5 }} }},
      y: {{ grid: {{ display: false }} }}
    }}
  }}
}});

// ── Word Cloud ──
(function() {{
  const cloud = document.getElementById('wordCloud');
  const maxFreq = WORD_FREQ.length > 0 ? WORD_FREQ[0][1] : 1;
  const colors = ['#3478F6', '#F59E0B', '#EF4444', '#22C55E', '#8B5CF6', '#f97316', '#6B7280'];
  WORD_FREQ.forEach(([word, freq], i) => {{
    const span = document.createElement('span');
    span.className = 'cloud-word';
    span.textContent = word;
    const scale = 0.6 + (freq / maxFreq) * 1.4;
    span.style.fontSize = (scale * 20) + 'px';
    span.style.color = colors[i % colors.length];
    cloud.appendChild(span);
  }});
}})();

// ── Cover Wall ──
(function() {{
  const wall = document.getElementById('coverWall');
  // 按时间倒序（新→旧）
  const sorted = [...NOTES].reverse();
  sorted.forEach(n => {{
    const div = document.createElement('div');
    div.className = 'cover-item';
    div.innerHTML = `
      <img src="${{n.cover_path}}" alt="${{n.title}}" loading="lazy">
      <span class="cover-type-badge ${{n.type}}">${{n.type === 'video' ? '▶ VIDEO' : '📷 IMAGE'}}</span>
      <div class="cover-overlay">
        <div>
          <div class="cover-overlay-text">${{n.title}}</div>
          <div class="cover-overlay-meta">${{n.date_str}} · ${{n.category}}</div>
        </div>
      </div>
    `;
    div.addEventListener('click', () => window.open(n.url, '_blank'));
    wall.appendChild(div);
  }});
}})();

// ── Top 10 ──
const HAS_REAL_LIKES = {str(data.get("has_real_likes", False)).lower()};
(function() {{
  const list = document.getElementById('topList');
  const formulaColors = {{}};
  FORMULAS.forEach(f => formulaColors[f.name] = f.color);

  // 有真实数据时按 likes 降序，否则保持预设主观排序
  let top10;
  if (HAS_REAL_LIKES) {{
    top10 = [...NOTES].sort((a, b) => (b.likes || 0) - (a.likes || 0)).slice(0, 10);
  }} else {{
    top10 = TOP10_IDS.map(idPrefix => NOTES.find(n => n.note_id.startsWith(idPrefix))).filter(Boolean).slice(0, 10);
  }}

  top10.forEach((note, idx) => {{
    const rank = idx + 1;
    const rankClass = rank === 1 ? 'gold' : rank === 2 ? 'silver' : rank === 3 ? 'bronze' : '';
    const tags = note.formulas.map(f =>
      `<span style="background:${{formulaColors[f] || '#333'}}20;color:${{formulaColors[f] || '#888'}};border:1px solid ${{formulaColors[f] || '#333'}}40">${{f}}</span>`
    ).join('');
    const likesStr = HAS_REAL_LIKES && note.likes > 0
      ? `<span style="color:var(--red);font-size:12px;font-family:var(--font-mono);margin-left:4px;">♥ ${{note.likes.toLocaleString()}}</span>`
      : '';

    // Find success factors from TOP10_ANALYSIS
    const analysis = TOP10_ANALYSIS.find(a => note.note_id.startsWith(a.note_id_prefix));
    const sfHtml = analysis ? `<div class="success-factors">${{analysis.success_factors}}</div>` : '';

    const div = document.createElement('div');
    div.className = 'card top-item animate-in';
    div.innerHTML = `
      <div class="top-rank ${{rankClass}}">${{String(rank).padStart(2, '0')}}</div>
      <img src="${{note.cover_path}}" alt="" loading="lazy">
      <div>
        <div class="top-title">${{note.title}}</div>
        <div class="top-tags">${{tags}}${{likesStr}}</div>
        ${{sfHtml}}
      </div>
      <span style="font-size:11px;color:var(--text-dim);font-family:var(--font-mono)">${{note.date_str}}</span>
    `;
    div.style.cursor = 'pointer';
    div.addEventListener('click', () => window.open(note.url, '_blank'));
    list.appendChild(div);
  }});
}})();

// ── Hit Patterns ──
(function() {{
  const box = document.getElementById('hitPatterns');
  if (!box || !HIT_PATTERNS || HIT_PATTERNS.length === 0) {{
    if (box) box.style.display = 'none';
    return;
  }}
  box.innerHTML = `<h4>爆款共性</h4><ul>${{HIT_PATTERNS.map(p => `<li>${{p}}</li>`).join('')}}</ul>`;
}})();

// ── Strategy Cards (always expanded) ──
(function() {{
  const list = document.getElementById('strategyList');
  STRATEGIES.forEach((s, i) => {{
    const div = document.createElement('div');
    div.className = 'strategy-item animate-in';
    div.innerHTML = `
      <div class="strategy-header">
        <span class="strategy-num">${{String(i + 1).padStart(2, '0')}}</span>
        <span class="strategy-title">${{s.title}}</span>
      </div>
      <div class="strategy-body">
        <p>${{s.body}}</p>
        <div class="strategy-action">📋 复制动作：${{s.action}}</div>
      </div>
    `;
    list.appendChild(div);
  }});
}})();

// ── Category Insights ──
(function() {{
  const grid = document.getElementById('categoryInsights');
  if (!grid || !CATEGORY_INSIGHTS) return;
  const colors = ['#3478F6', '#F59E0B', '#EF4444', '#22C55E', '#8B5CF6', '#9CA3AF'];
  Object.entries(CATEGORY_INSIGHTS).forEach(([cat, text], i) => {{
    const div = document.createElement('div');
    div.className = 'cat-insight-card';
    div.innerHTML = `<h4 style="border-left:3px solid ${{colors[i % colors.length]}};padding-left:10px;">${{cat}}</h4><p>${{text}}</p>`;
    grid.appendChild(div);
  }});
}})();

// ── Format Comparison ──
(function() {{
  if (!FORMAT_COMPARISON || !FORMAT_COMPARISON.video_avg_likes) return;
  const vEl = document.getElementById('fmtVideoLikes');
  const iEl = document.getElementById('fmtImageLikes');
  const insEl = document.getElementById('fmtInsight');
  if (vEl) vEl.textContent = FORMAT_COMPARISON.video_avg_likes;
  if (iEl) iEl.textContent = FORMAT_COMPARISON.image_avg_likes;
  if (insEl) insEl.textContent = FORMAT_COMPARISON.insight || '';
  const tbody = document.querySelector('#fmtTable tbody');
  if (tbody && FORMAT_COMPARISON.per_category) {{
    FORMAT_COMPARISON.per_category.forEach(row => {{
      const tr = document.createElement('tr');
      const fmtColor = row.best_format === '视频' ? 'var(--blue)' : row.best_format === '图文' ? 'var(--amber)' : 'var(--purple)';
      tr.innerHTML = `<td>${{row.category}}</td><td style="color:${{fmtColor}};font-weight:600;">${{row.best_format}}</td><td style="color:var(--text-dim);">${{row.reason}}</td>`;
      tbody.appendChild(tr);
    }});
  }}
}})();

// ── Hit vs Miss Table ──
(function() {{
  if (!TITLE_HIT_VS_MISS || !TITLE_HIT_VS_MISS.dimensions) {{
    const wrap = document.getElementById('hvmWrap');
    if (wrap) wrap.style.display = 'none';
    return;
  }}
  const tbody = document.querySelector('#hvmTable tbody');
  if (!tbody) return;
  TITLE_HIT_VS_MISS.dimensions.forEach((dim, i) => {{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="dim-cell">${{dim}}</td><td class="hit-cell">${{TITLE_HIT_VS_MISS.hit[i] || ''}}</td><td class="miss-cell">${{TITLE_HIT_VS_MISS.miss[i] || ''}}</td>`;
    tbody.appendChild(tr);
  }});
}})();

// ── Cover Analysis ──
(function() {{
  if (!COVER_ANALYSIS || !COVER_ANALYSIS.styles) {{
    ['coverStyles', 'coverPatternsWrap', 'coverTemplate'].forEach(id => {{
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    }});
    return;
  }}
  // Style cards
  const grid = document.getElementById('coverStyles');
  if (grid) {{
    COVER_ANALYSIS.styles.forEach(s => {{
      const likesBadge = s.avg_likes ? `<span class="count-badge" style="background:rgba(239,68,68,0.08);color:#EF4444;">♥ 均 ${{s.avg_likes}}</span>` : '';
      const div = document.createElement('div');
      div.className = 'cover-style-card';
      div.innerHTML = `
        <h4>${{s.name}} <span class="count-badge">${{s.count}} 篇</span> ${{likesBadge}} <span class="perf-badge perf-${{s.performance}}">${{s.performance}}</span></h4>
        <p style="font-size:13px;color:var(--text-dim);line-height:1.6;">${{s.traits}}</p>
      `;
      grid.appendChild(div);
    }});
  }}
  // Hit patterns
  const patList = document.getElementById('coverPatterns');
  if (patList && COVER_ANALYSIS.hit_cover_patterns) {{
    COVER_ANALYSIS.hit_cover_patterns.forEach(p => {{
      const li = document.createElement('li');
      li.textContent = p;
      patList.appendChild(li);
    }});
  }}
  // Template
  const tmplText = document.getElementById('coverTemplateText');
  if (tmplText && COVER_ANALYSIS.template_suggestion) {{
    tmplText.textContent = COVER_ANALYSIS.template_suggestion;
  }}
}})();

// ── Formulas Recap ──
(function() {{
  const grid = document.getElementById('formulasRecap');
  if (!grid || !CONTENT_FORMULAS_RECAP || CONTENT_FORMULAS_RECAP.length === 0) return;
  CONTENT_FORMULAS_RECAP.forEach(f => {{
    const div = document.createElement('div');
    div.className = 'formula-recap-card';
    div.innerHTML = `<div class="recap-label">${{f.label}}</div><div class="recap-template">${{f.template}}</div>`;
    grid.appendChild(div);
  }});
}})();

// ── Action Plan ──
(function() {{
  const container = document.getElementById('actionPlan');
  if (!container || !ACTION_PLAN) return;
  const sections = [
    {{ key: 'this_week', title: '本周', cls: 'week', icon: '🎯' }},
    {{ key: 'this_month', title: '本月', cls: 'month', icon: '📅' }},
    {{ key: 'long_term', title: '长期', cls: 'long', icon: '🚀' }},
  ];
  sections.forEach(sec => {{
    const items = ACTION_PLAN[sec.key] || [];
    if (items.length === 0) return;
    const col = document.createElement('div');
    col.className = `action-col ${{sec.cls}}`;
    const priorityBadge = sec.cls === 'week' ? '<span style="font-size:10px;background:rgba(255,255,255,0.25);padding:2px 8px;border-radius:4px;margin-left:auto;letter-spacing:1px;">PRIORITY</span>' : '';
    col.innerHTML = `<h4>${{sec.icon}} ${{sec.title}}${{priorityBadge}}</h4><ul>${{items.map(item => `<li>${{item}}</li>`).join('')}}</ul>`;
    container.appendChild(col);
  }});
}})();

// ── Scroll Animation (IntersectionObserver) ──
const observer = new IntersectionObserver(
  entries => entries.forEach(e => {{
    if (e.isIntersecting) {{
      e.target.classList.add('visible');
      observer.unobserve(e.target);
    }}
  }}),
  {{ threshold: 0.1, rootMargin: '0px 0px -40px 0px' }}
);
document.querySelectorAll('.animate-in').forEach(el => observer.observe(el));

// ── Staggered animation delays ──
document.querySelectorAll('.kpi-grid .card').forEach((el, i) => {{
  el.style.transitionDelay = (i * 0.1) + 's';
}});
document.querySelectorAll('.formulas-grid .card').forEach((el, i) => {{
  el.style.transitionDelay = (i * 0.08) + 's';
}});
document.querySelectorAll('.cover-item').forEach((el, i) => {{
  el.style.animationDelay = (i * 0.02) + 's';
}});
</script>
</body>
</html>'''


# ── 主入口 ────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("用法: python3 generate_dashboard.py <account_id>")
        print("示例: python3 generate_dashboard.py 584e091082ec393a36072547")
        sys.exit(1)

    account_id = sys.argv[1]
    account_dir = DATA_DIR / account_id

    if not account_dir.exists():
        print(f"错误: 账号数据目录不存在: {account_dir}")
        sys.exit(1)

    print(f"📊 加载数据: {account_id}")
    profile, notes = load_data(account_id)
    analysis = load_analysis(account_id)

    print(f"🔍 处理 {len(notes)} 篇笔记...")
    data = process_data(profile, notes, analysis)

    # 优先使用本地头像文件（CDN 链接可能因防盗链失效）
    avatar_local = account_dir / "avatar.jpg"
    if avatar_local.exists():
        data["profile"]["avatar_url"] = "avatar.jpg"

    print("🎨 生成看板 HTML...")
    html = generate_html(data)

    output_path = account_dir / "dashboard.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ 看板已生成: {output_path}")
    print(f"   文件大小: {os.path.getsize(output_path) / 1024:.0f} KB")
    print(f"\n⚠️  本地图片需要 HTTP 服务器才能正常显示，请用以下命令打开：")
    print(f"   cd {account_dir} && python3 -m http.server 8765")
    print(f"   然后访问 http://localhost:8765/dashboard.html")


if __name__ == "__main__":
    main()
