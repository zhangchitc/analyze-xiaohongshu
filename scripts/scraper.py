#!/usr/bin/env python3
"""
小红书账号爬虫 - Playwright 实现
功能：爬取指定账号的主页信息和所有笔记卡片数据（含封面图）
策略：仅在账号主页操作，不访问任何笔记详情页，规避反爬检测
"""

import asyncio
import json
import os
import re
import random
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ─── 配置 ─────────────────────────────────────────────────────────────────────

BASE_DATA_DIR = Path(__file__).parent.parent / "data"
COOKIES_FILE = BASE_DATA_DIR / "cookies.json"
MAX_NOTES = 500          # 最多爬取笔记数
DELAY_MIN = 2.0          # 请求间最小延迟（秒）
DELAY_MAX = 5.0          # 请求间最大延迟（秒）
MAX_RETRIES = 3          # 单个请求最大重试次数
SCROLL_PAUSE = 1.5       # 滚动等待时间


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def parse_account_id(input_str: str) -> str:
    """从链接或直接 ID 中解析账号 ID"""
    input_str = input_str.strip()
    # 匹配形如 /user/profile/xxx 的 URL
    match = re.search(r'/user/profile/([a-zA-Z0-9]+)', input_str)
    if match:
        return match.group(1)
    # 直接输入 ID
    if re.match(r'^[a-zA-Z0-9]+$', input_str):
        return input_str
    raise ValueError(f"无法解析账号 ID：{input_str}")


def parse_count(s: str) -> int:
    """解析中文数字字符串（支持'万'）"""
    s = str(s).strip().replace(',', '')
    if '万' in s:
        return int(float(s.replace('万', '')) * 10000)
    try:
        return int(s)
    except Exception:
        return 0


def random_delay():
    """随机延迟，模拟人工操作"""
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def save_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: Path):
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


async def download_image(page, url: str, save_path: Path, retries: int = MAX_RETRIES) -> bool:
    """下载图片到本地"""
    save_path.parent.mkdir(parents=True, exist_ok=True)
    if save_path.exists():
        return True  # 断点续传：已存在则跳过
    for attempt in range(retries):
        try:
            response = await page.request.get(url, timeout=15000)
            if response.ok:
                content = await response.body()
                save_path.write_bytes(content)
                return True
        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(random.uniform(1, 3))
            else:
                print(f"  [警告] 下载图片失败 {url}: {e}")
    return False


# ─── Cookie 管理 ──────────────────────────────────────────────────────────────

async def load_cookies(context):
    """加载已保存的 cookie"""
    data = load_json(COOKIES_FILE)
    if data:
        await context.add_cookies(data)
        return True
    return False


async def save_cookies(context):
    """保存当前 cookie"""
    cookies = await context.cookies()
    COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    save_json(cookies, COOKIES_FILE)


async def is_logged_in(page) -> bool:
    """检查是否已登录"""
    try:
        await page.goto('https://www.xiaohongshu.com', timeout=15000)
        await page.wait_for_load_state('networkidle', timeout=10000)
        # 已登录时页面不会有登录按钮
        login_btn = page.locator('text=登录')
        count = await login_btn.count()
        return count == 0
    except Exception:
        return False


async def do_login(page, context):
    """打开登录页，等待用户手动扫码登录"""
    print("\n[登录] 正在打开小红书登录页，请在浏览器中扫码登录...")
    await page.goto('https://www.xiaohongshu.com', timeout=15000)
    await page.wait_for_load_state('networkidle', timeout=15000)
    await asyncio.sleep(5)  # 等待页面稳定及所有跳转完成

    print("[登录] 等待扫码登录（最多 3 分钟）...")
    print("[登录] 请在浏览器中扫描二维码，扫码后无需任何操作...")

    deadline = time.time() + 180
    while time.time() < deadline:
        await asyncio.sleep(5)
        cookies = await context.cookies()
        # 检查核心登录 cookie：web_session 存在且有值
        has_session = any(
            c['name'] == 'web_session' and c.get('value', '')
            for c in cookies
        )
        current_url = page.url
        # 只有 cookie 存在 且 已离开 /login 页面，才算真正登录成功
        if has_session and '/login' not in current_url:
            print("[登录] 登录成功！")
            await save_cookies(context)
            return True
        remaining = int(deadline - time.time())
        if remaining > 0:
            print(f"  等待中... 还剩约 {remaining}s")

    raise TimeoutError("登录超时，请重试")


# ─── 账号主页爬取 ─────────────────────────────────────────────────────────────

async def goto_stable(page, url: str, timeout: int = 30000):
    """导航到目标 URL，等待页面稳定在该 URL（绕过小红书反爬跳转循环）"""
    await page.goto(url, timeout=timeout)
    # 等待最终 URL 稳定在目标页面（可能经历重定向）
    try:
        await page.wait_for_url(
            re.compile(re.escape(url.split('?')[0])),
            timeout=20000,
        )
    except PlaywrightTimeoutError:
        pass  # 超时则继续，用当前页面状态
    await page.wait_for_load_state('networkidle', timeout=15000)
    await asyncio.sleep(3)


async def scrape_profile(page, account_id: str) -> dict:
    """爬取账号基本信息，同时拦截 API 响应获取结构化数据"""
    url = f'https://www.xiaohongshu.com/user/profile/{account_id}'
    print(f"\n[主页] 访问 {url}")

    # 拦截 profile API 响应
    api_profile: dict = {}

    async def on_response(response):
        try:
            if ('userinfo' in response.url or 'otherinfo' in response.url
                    or 'user/profile' in response.url) and response.status == 200:
                body = await response.json()
                # 兼容多种响应结构
                data = body.get('data', body)
                if isinstance(data, dict):
                    user = data.get('basic_info') or data.get('user') or data
                    if isinstance(user, dict):
                        api_profile.update(user)
        except Exception:
            pass

    page.on('response', on_response)
    await goto_stable(page, url)
    await asyncio.sleep(2)  # 等待 API 响应完成
    page.remove_listener('response', on_response)

    profile = {'account_id': account_id, 'url': url}

    # ── 头像 ──
    try:
        # 优先从 API 获取头像（imageb 是大图，images 是小图）
        api_avatar = api_profile.get('imageb') or api_profile.get('images') or ''
        # 从 DOM 获取头像（更精确的选择器）
        dom_avatar = ''
        for selector in [
            '.user-info img[class*="avatar"]',
            '.info-part img[class*="avatar"]',
            'img[class*="avatar"][src*="avatar"]',
            'img[class*="avatar"]',
        ]:
            el = page.locator(selector).first
            if await el.count() > 0:
                s = await el.get_attribute('src') or ''
                if s and '/avatar/' in s:
                    dom_avatar = s
                    break
        raw_url = api_avatar or dom_avatar
        # 将缩略图 URL 升级为大图（/w/60 → /w/360）
        if raw_url and '/w/' in raw_url:
            raw_url = re.sub(r'/w/\d+', '/w/360', raw_url)
        profile['avatar_url'] = raw_url
    except Exception:
        profile['avatar_url'] = api_profile.get('imageb', '')

    # ── 昵称 ──
    try:
        nickname_el = page.locator('.user-name, .username, [class*="nickname"]').first
        dom_name = await nickname_el.inner_text() if await nickname_el.count() > 0 else ''
        profile['nickname'] = api_profile.get('nickname') or dom_name
    except Exception:
        profile['nickname'] = api_profile.get('nickname', '')

    # ── 小红书号 ──
    try:
        xhs_id_el = page.locator('text=/小红书号/').first
        xhs_id_text = await xhs_id_el.inner_text() if await xhs_id_el.count() > 0 else ''
        match = re.search(r'小红书号[：:]\s*(\S+)', xhs_id_text)
        profile['xiaohongshu_id'] = api_profile.get('red_id') or (match.group(1) if match else '')
    except Exception:
        profile['xiaohongshu_id'] = api_profile.get('red_id', '')

    # ── 简介 ──
    try:
        bio_el = page.locator('.user-desc, [class*="desc"]').first
        dom_bio = await bio_el.inner_text() if await bio_el.count() > 0 else ''
        profile['bio'] = api_profile.get('desc') or dom_bio
    except Exception:
        profile['bio'] = api_profile.get('desc', '')

    # ── IP 属地 ──
    try:
        ip_el = page.locator('text=/IP 属地/, text=/ip属地/i').first
        ip_text = await ip_el.inner_text() if await ip_el.count() > 0 else ''
        match = re.search(r'IP\s*属地[：:\s]*(.+)', ip_text, re.IGNORECASE)
        profile['ip_location'] = (
            api_profile.get('ip_location') or (match.group(1).strip() if match else '')
        )
    except Exception:
        profile['ip_location'] = api_profile.get('ip_location', '')

    # ── 粉丝/关注/获赞收藏数 ──
    try:
        stat_els = page.locator('[class*="count"], [class*="num"]')
        stats_text = []
        for i in range(min(await stat_els.count(), 6)):
            text = await stat_els.nth(i).inner_text()
            stats_text.append(text.strip())
        profile['stats_raw'] = stats_text
    except Exception:
        profile['stats_raw'] = []

    print(f"  昵称: {profile.get('nickname', '(未获取)')}")
    print(f"  IP属地: {profile.get('ip_location', '(未获取)')}")
    print(f"  头像: {'✓' if profile.get('avatar_url') else '✗'}")
    return profile


# ─── 笔记列表爬取 ─────────────────────────────────────────────────────────────

def _extract_notes_from_api_body(body: dict) -> list[dict]:
    """从 API 响应中提取笔记数据，兼容多种字段路径"""
    candidates = []
    # 常见路径
    for key in ('notes', 'items', 'data'):
        val = body.get(key) or body.get('data', {}).get(key, [])
        if isinstance(val, list) and val:
            candidates = val
            break
    if not candidates:
        # 递归搜索第一个 list 类型的值（最多两层）
        for v in body.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                candidates = v
                break
            if isinstance(v, dict):
                for vv in v.values():
                    if isinstance(vv, list) and vv and isinstance(vv[0], dict):
                        candidates = vv
                        break
    return candidates


def _first_non_none(*values):
    """返回第一个非 None 的值（0 也是有效值）"""
    for v in values:
        if v is not None:
            return v
    return 0


def _parse_api_note(item: dict) -> dict | None:
    """将 API 笔记对象解析为标准字段，note_id 无法确定时返回 None"""
    note_id = (
        item.get('note_id') or item.get('id')
        or item.get('noteId') or item.get('note', {}).get('note_id')
    )
    if not note_id:
        return None

    # 互动数（兼容多种命名，0 是有效值不可跳过）
    interact = item.get('interact_info') or item.get('interactInfo') or item
    likes = _first_non_none(
        interact.get('liked_count'), interact.get('likedCount'),
        interact.get('like_count'), interact.get('likeCount'),
    )
    collects = _first_non_none(
        interact.get('collected_count'), interact.get('collectedCount'),
        interact.get('collect_count'), interact.get('collectCount'),
    )
    comments = _first_non_none(
        interact.get('comment_count'), interact.get('commentCount'),
        interact.get('comments'),
    )
    shares = _first_non_none(
        interact.get('share_count'), interact.get('shareCount'),
    )

    # 视频时长（秒），兼容多种路径
    video_info = item.get('video') or item.get('video_info') or {}
    duration = int(
        video_info.get('duration') or video_info.get('capa', {}).get('duration', 0) or 0
    )

    # 图片数
    images = item.get('image_list') or item.get('imageList') or []
    image_count = len(images)

    # 类型
    note_type = item.get('type') or item.get('note_type') or ''
    if not note_type:
        note_type = 'video' if duration > 0 or video_info else 'image'

    # 封面
    cover = item.get('cover') or item.get('image_info', {}) or {}
    cover_url = (
        cover.get('url') or cover.get('url_default')
        or (images[0].get('url') if images else '')
        or ''
    )

    # 标题
    title = item.get('title') or item.get('display_title') or ''

    return {
        'note_id': note_id,
        'url': f'https://www.xiaohongshu.com/explore/{note_id}',
        'title': title.strip(),
        'cover_url': cover_url,
        'likes': parse_count(str(likes)),
        'collects': parse_count(str(collects)),
        'comments': parse_count(str(comments)),
        'shares': parse_count(str(shares)),
        'type': note_type.lower(),
        'video_duration': duration,   # 秒，0 表示非视频或未知
        'image_count': image_count,   # 0 表示非多图或未知
    }


async def scrape_note_list(page, account_id: str) -> list[dict]:
    """
    滚动加载账号主页，获取笔记卡片列表。
    策略：优先拦截 API JSON 响应（含真实互动数据），
         DOM 解析作为 cover_url / 类型的补充兜底。
    """
    url = f'https://www.xiaohongshu.com/user/profile/{account_id}'

    # ── API 拦截：收集所有笔记 API 响应 ──────────────────────────────
    api_notes: dict[str, dict] = {}   # note_id → parsed note

    async def on_response(response):
        try:
            resp_url = response.url
            # 只处理 JSON API 响应（排除图片/css/字体）
            ct = response.headers.get('content-type', '')
            if 'json' not in ct and 'javascript' not in ct:
                return
            if response.status != 200:
                return
            # 关键词过滤，减少无关解析
            if not any(k in resp_url for k in ('user_posted', 'posted', 'notes', 'profile', 'user/otherinfo', 'homefeed')):
                return
            body = await response.json()
            items = _extract_notes_from_api_body(body)
            if items:
                print(f"  [API] 拦截到 {len(items)} 条笔记数据 ({resp_url[:80]}...)")
            for item in items:
                parsed = _parse_api_note(item)
                if parsed and parsed['note_id'] not in api_notes:
                    api_notes[parsed['note_id']] = parsed
        except Exception as e:
            # 只记录与笔记 API 相关的错误
            if any(k in response.url for k in ('user_posted', 'posted', 'notes')):
                print(f"  [API 警告] 解析失败: {e} ({response.url[:80]})")

    page.on('response', on_response)
    await goto_stable(page, url)

    # ── DOM 解析 + 滚动 ───────────────────────────────────────────────
    dom_notes: dict[str, dict] = {}   # note_id → dom info（cover_url / type 兜底）
    scroll_count = 0
    max_scrolls = 30
    prev_dom_count = 0

    print(f"\n[笔记列表] 开始滚动加载...")

    while len(dom_notes) < MAX_NOTES and scroll_count < max_scrolls:
        note_cards = page.locator('section.note-item')
        count = await note_cards.count()
        if count == 0:
            note_cards = page.locator('a[href*="/explore/"]')
            count = await note_cards.count()

        for i in range(count):
            try:
                card = note_cards.nth(i)
                link_el = card.locator('a[href*="/explore/"]').first
                href = (
                    await link_el.get_attribute('href')
                    if await link_el.count() > 0
                    else await card.get_attribute('href') or ''
                )
                m = re.search(r'/explore/([a-zA-Z0-9]+)', href or '')
                if not m:
                    continue
                note_id = m.group(1)
                if note_id in dom_notes:
                    continue

                # 封面
                cover_el = card.locator('img').first
                cover_url = (
                    await cover_el.get_attribute('src')
                    if await cover_el.count() > 0 else ''
                ) or ''

                # 标题（DOM 兜底）
                title_el = card.locator('[class*="title"], [class*="desc"]').first
                title = await title_el.inner_text() if await title_el.count() > 0 else ''

                # 类型（DOM 兜底）
                video_el = card.locator('[class*="video"], [class*="play"]')
                note_type = 'video' if await video_el.count() > 0 else 'image'

                # 视频时长（DOM：卡片左下角文字如 "02:34"）
                duration_el = card.locator('[class*="duration"], [class*="time"]').first
                duration_text = (
                    await duration_el.inner_text() if await duration_el.count() > 0 else ''
                )
                video_duration = 0
                if duration_text:
                    parts = duration_text.strip().split(':')
                    try:
                        if len(parts) == 2:
                            video_duration = int(parts[0]) * 60 + int(parts[1])
                        elif len(parts) == 3:
                            video_duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    except ValueError:
                        pass

                # 点赞数（DOM 兜底，尝试多个选择器）
                likes = 0
                for sel in (
                    '.like-wrapper .count',
                    '[class*="like-count"]',
                    '[class*="likeCount"]',
                    '.footer-count',
                    '[class*="like"] span',
                    '.note-metrics span',
                    'span.count',
                    '.engage-bar span',
                    '.interact-info span',
                ):
                    likes_el = card.locator(sel).first
                    if await likes_el.count() > 0:
                        likes_text = await likes_el.inner_text()
                        likes = parse_count(likes_text)
                        if likes > 0:
                            break
                # 最后兜底：在卡片底部区域查找数字文本
                if likes == 0:
                    try:
                        footer_el = card.locator('.footer, [class*="footer"], [class*="interact"]').first
                        if await footer_el.count() > 0:
                            footer_text = await footer_el.inner_text()
                            # 匹配形如 "1234" 或 "1.2万" 的数字
                            m = re.search(r'(\d[\d.]*万?)', footer_text)
                            if m:
                                likes = parse_count(m.group(1))
                    except Exception:
                        pass

                # 多图标记
                multi_el = card.locator('[class*="multi"], [class*="carousel"], [class*="count"][class*="image"]')
                image_count = 1 if await multi_el.count() > 0 else 0

                dom_notes[note_id] = {
                    'note_id': note_id,
                    'url': f'https://www.xiaohongshu.com/explore/{note_id}',
                    'title': title.strip(),
                    'cover_url': cover_url,
                    'likes': likes,
                    'collects': 0,
                    'comments': 0,
                    'shares': 0,
                    'type': note_type,
                    'video_duration': video_duration,
                    'image_count': image_count,
                }
            except Exception:
                continue

        if len(dom_notes) >= MAX_NOTES:
            break

        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await asyncio.sleep(SCROLL_PAUSE)
        scroll_count += 1

        new_count = await page.locator('section.note-item').count()
        if new_count == 0:
            new_count = await page.locator('a[href*="/explore/"]').count()
        print(f"  滚动 {scroll_count}: DOM {len(dom_notes)} 篇 / API {len(api_notes)} 篇")

        if new_count <= prev_dom_count and scroll_count > 3:
            break
        prev_dom_count = new_count

    page.remove_listener('response', on_response)

    # ── 合并：API 数据优先，DOM 补充缺失字段 ──────────────────────────
    merged: list[dict] = []
    all_ids = list(dict.fromkeys(list(dom_notes.keys()) + list(api_notes.keys())))
    for note_id in all_ids[:MAX_NOTES]:
        api = api_notes.get(note_id, {})
        dom = dom_notes.get(note_id, {})
        note = {**dom, **{k: v for k, v in api.items() if v is not None}}  # API 覆盖 DOM
        # cover_url 优先用 DOM（已下载的高质量 CDN URL）
        if dom.get('cover_url'):
            note['cover_url'] = dom['cover_url']
        if note:
            merged.append(note)

    # 统计 API 命中情况
    api_hit = sum(1 for n in merged if n.get('likes', 0) > 0 or api_notes.get(n['note_id']))
    print(f"\n  共 {len(merged)} 篇笔记，API 命中 {len(api_notes)} 篇，DOM 点赞>0: {api_hit} 篇")
    return merged


# ─── 主流程 ──────────────────────────────────────────────────────────────────

async def main(account_input: str):
    account_id = parse_account_id(account_input)
    print(f"\n=== 开始爬取账号: {account_id} ===")
    print("[策略] 仅爬取主页卡片数据，不访问笔记详情页")

    account_dir = BASE_DATA_DIR / account_id
    covers_dir = account_dir / 'covers'
    profile_path = account_dir / 'profile.json'
    notes_path = account_dir / 'notes.json'

    account_dir.mkdir(parents=True, exist_ok=True)
    covers_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=['--no-sandbox'])
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        # ── 登录 ──
        cookies_loaded = await load_cookies(context)
        logged_in = cookies_loaded and await is_logged_in(page)

        if not logged_in:
            await do_login(page, context)
        else:
            print("[登录] 使用已保存的 Cookie，已登录")

        # ── 爬取主页 ──
        profile = await scrape_profile(page, account_id)
        save_json(profile, profile_path)
        print(f"[主页] 已保存 → {profile_path}")

        # ── 下载头像 ──
        avatar_path = account_dir / 'avatar.jpg'
        if profile.get('avatar_url') and not avatar_path.exists():
            ok = await download_image(page, profile['avatar_url'], avatar_path)
            # 验证头像：太小（<5KB）可能是默认占位图，删除
            if ok and avatar_path.exists() and avatar_path.stat().st_size < 5120:
                avatar_path.unlink()
                ok = False
                print(f"[头像] ✗ 疑似默认头像，已跳过")
            else:
                print(f"[头像] {'✓ 已下载' if ok else '✗ 下载失败'}")
        random_delay()

        # ── 获取笔记列表（含封面、标题、点赞数、类型） ──
        note_list = await scrape_note_list(page, account_id)

        # ── 合并：更新已有笔记的互动数据，添加新笔记 ──
        existing_notes = load_json(notes_path) or []
        existing_map = {n['note_id']: n for n in existing_notes}
        fresh_map = {n['note_id']: n for n in note_list}

        # 更新已有笔记的互动数据（likes/collects/comments/shares）
        ENGAGEMENT_KEYS = ('likes', 'collects', 'comments', 'shares', 'video_duration', 'image_count')
        updated_count = 0
        for note_id, fresh in fresh_map.items():
            if note_id in existing_map:
                old = existing_map[note_id]
                for key in ENGAGEMENT_KEYS:
                    fresh_val = fresh.get(key, 0)
                    old_val = old.get(key, 0)
                    # 用更大的值更新（互动数只增不减）
                    if fresh_val > old_val:
                        old[key] = fresh_val
                        updated_count += 1
                # 也更新标题（可能之前是空的）
                if fresh.get('title') and not old.get('title'):
                    old['title'] = fresh['title']

        new_notes = [n for n in note_list if n['note_id'] not in existing_map]
        if updated_count:
            print(f"\n[更新] 已更新 {updated_count} 项互动数据")
        print(f"[封面] 下载 {len(new_notes)} 张新封面（已有 {len(existing_map)} 篇）")

        # ── 下载封面图（仅新笔记） ──
        all_notes = list(existing_map.values())
        for i, note in enumerate(new_notes, 1):
            note_id = note['note_id']
            cover_path = covers_dir / f"{note_id}.jpg"
            note['cover_local_path'] = str(cover_path)

            if note.get('cover_url') and not cover_path.exists():
                print(f"[封面 {i}/{len(new_notes)}] {note_id} - {note.get('title', '')[:30]}")
                await download_image(page, note['cover_url'], cover_path)

            all_notes.append(note)

            # 每下载 20 张保存一次进度
            if i % 20 == 0:
                save_json(all_notes, notes_path)
                print(f"  [进度保存] {len(all_notes)} 篇")

        # ── 最终保存 ──
        save_json(all_notes, notes_path)
        print(f"\n[完成] 共爬取 {len(all_notes)} 篇笔记")
        print(f"  数据: {notes_path}")
        print(f"  封面: {covers_dir}")

        await browser.close()

    return account_id, str(account_dir)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python scraper.py <账号链接或ID>")
        print("示例: python scraper.py https://www.xiaohongshu.com/user/profile/abc123")
        sys.exit(1)

    account_id, data_dir = asyncio.run(main(sys.argv[1]))
    print(f"\n爬取完成！账号 ID: {account_id}")
    print(f"数据目录: {data_dir}")
