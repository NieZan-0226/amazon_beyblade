#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amazon Japan Beyblade X search watcher.

監控 Amazon.co.jp 搜尋結果，偵測新出現、重新出現、價格下降與消失的商品。
不需要 Playwright；只使用 requests 讀取 Amazon 搜尋結果 HTML。
"""

from __future__ import annotations

import html
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests


SEARCH_URL = os.environ.get(
    "AMAZON_SEARCH_URL",
    "https://www.amazon.co.jp/s?k=takara+tomy+beyblade+x&i=toys&rh=n%3A13299531%2Cp_123%3A1432576&dc&language=zh&ref=sr_nr_p_123_1",
)
SOURCE_NAME = "Amazon JP"
DEFAULT_TOPIC = "amazon-beyblade-x-tw-9q4m7z2k"

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or DEFAULT_TOPIC
STATE_FILE = Path(os.environ.get("STATE_FILE", "tracked_items.json"))
FEED_FILE = Path(os.environ.get("FEED_FILE", "feed.json"))
HISTORY_FILE = Path(os.environ.get("HISTORY_FILE", "history.jsonl"))
WATCHLIST_FILE = Path(os.environ.get("WATCHLIST_FILE", "watchlist.json"))

HISTORY_RETENTION_HOURS = int(os.environ.get("HISTORY_RETENTION_HOURS", "24"))
FAIL_ALERT_THRESHOLD = int(os.environ.get("FAIL_ALERT_THRESHOLD", "3"))
FLOOD_THRESHOLD = int(os.environ.get("FLOOD_THRESHOLD", "8"))
NOTIFY_PRICE_DROP = os.environ.get("NOTIFY_PRICE_DROP", "1") == "1"
DEBUG = os.environ.get("DEBUG", "0") == "1"
META_KEY = "__meta__"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def split_meta(state: dict) -> tuple[dict, dict]:
    state = dict(state or {})
    meta = state.pop(META_KEY, {})
    if not isinstance(meta, dict):
        meta = {}
    return state, meta


def save_state_with_meta(products: dict, meta: dict) -> None:
    out = dict(products)
    out[META_KEY] = meta
    write_json(STATE_FILE, out)


def download_html() -> str:
    last_error = None
    for attempt in range(1, 4):
        try:
            resp = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            text = resp.text
            if re.search(r"Robot Check|captcha|輸入您看到的字元", text, re.I):
                raise RuntimeError("Amazon 回傳 CAPTCHA / Robot Check，暫時無法解析。")
            if "s-search-result" not in text and "data-asin=" not in text:
                raise RuntimeError("Amazon 搜尋頁沒有出現商品卡，可能版型改變或被導向。")
            return text
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep((2 ** attempt) + random.random())
    raise RuntimeError(str(last_error))


def strip_tags(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def attr(block: str, name: str) -> str:
    m = re.search(rf'{re.escape(name)}="([^"]*)"', block)
    return html.unescape(m.group(1)) if m else ""


def parse_price(block: str) -> float | None:
    offscreen = re.search(r'<span class="a-offscreen">\s*(?:TWD|￥|¥)?\s*([\d,]+(?:\.\d+)?)\s*</span>', block)
    if offscreen:
        try:
            return float(offscreen.group(1).replace(",", ""))
        except ValueError:
            return None

    whole = re.search(r'<span class="a-price-whole">([\d,\.]+)</span>', block)
    frac = re.search(r'<span class="a-price-fraction">(\d+)</span>', block)
    if whole:
        raw = whole.group(1).replace(",", "").replace(".", "")
        if frac:
            raw = f"{raw}.{frac.group(1)}"
        try:
            return float(raw)
        except ValueError:
            return None

    # fallback：搜尋區塊內的￥ / ¥ / 円文字價格
    text = strip_tags(block)
    m = re.search(r"[￥¥]\s*([\d,]+)", text) or re.search(r"([\d,]+)\s*円", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_title(block: str) -> str:
    patterns = [
        r'<h2[^>]*aria-label="([^"]+)"',
        r'<h2[\s\S]*?<span[^>]*>([\s\S]*?)</span>',
        r'<img[^>]+alt="([^"]+)"',
    ]
    for pattern in patterns:
        m = re.search(pattern, block, re.I)
        if m:
            title = strip_tags(html.unescape(m.group(1)))
            if title:
                return title
    return ""


def parse_url(block: str, asin: str) -> str:
    m = re.search(r'<a[^>]+href="([^"]*(?:/dp/|/gp/product/)[^"]*)"', block, re.I)
    if m:
        return urljoin("https://www.amazon.co.jp", html.unescape(m.group(1)))
    return f"https://www.amazon.co.jp/dp/{asin}?language=zh"


def parse_image(block: str) -> str:
    m = re.search(r'<img[^>]+class="[^"]*\bs-image\b[^"]*"[^>]+src="([^"]+)"', block, re.I)
    return html.unescape(m.group(1)) if m else ""


def parse_products(page_html: str) -> list[dict]:
    starts = [m.start() for m in re.finditer(r'data-component-type="s-search-result"', page_html)]
    products = []
    seen = set()
    for idx, start in enumerate(starts):
        block_start = page_html.rfind("<div", 0, start)
        block_end = starts[idx + 1] if idx + 1 < len(starts) else page_html.find("</body", start)
        if block_start < 0 or block_end < 0:
            continue
        block = page_html[block_start:block_end]
        asin = attr(block, "data-asin")
        if not asin or asin in seen:
            continue
        title = parse_title(block)
        if not title:
            continue
        seen.add(asin)
        price = parse_price(block)
        products.append({
            "key": asin,
            "title": title,
            "url": parse_url(block, asin),
            "price": price,
            "in_stock": price is not None and "目前無法購買" not in strip_tags(block),
            "image": parse_image(block),
        })
    return products


def load_watchlist() -> list[str]:
    data = read_json(WATCHLIST_FILE, [])
    if isinstance(data, dict):
        data = data.get("keywords", [])
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()]


def matched_keyword(title: str, keywords: list[str]) -> str | None:
    lower = (title or "").lower()
    for keyword in keywords:
        if keyword.lower() in lower:
            return keyword
    return None


def append_history(current: dict, ts: str) -> None:
    rows = [
        json.dumps({
            "ts": ts,
            "id": p["key"],
            "title": p["title"],
            "price": p.get("price"),
            "in_stock": p.get("in_stock", True),
        }, ensure_ascii=False)
        for p in current.values()
    ]
    if rows:
        with HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write("\n".join(rows) + "\n")
    prune_history(ts)


def parse_ts(value: str):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def prune_history(ts: str) -> None:
    if HISTORY_RETENTION_HOURS <= 0 or not HISTORY_FILE.exists():
        return
    base = parse_ts(ts) or datetime.now(timezone.utc)
    cutoff = base - timedelta(hours=HISTORY_RETENTION_HOURS)
    kept = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row_ts = parse_ts(row.get("ts"))
        if row_ts and row_ts >= cutoff:
            kept.append(json.dumps(row, ensure_ascii=False))
    HISTORY_FILE.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


def write_feed(current: dict, new_keys=(), restock_keys=()) -> None:
    new_keys, restock_keys = set(new_keys), set(restock_keys)
    products = []
    for key, p in current.items():
        status = "new" if key in new_keys else "restock" if key in restock_keys else "normal"
        item = dict(p)
        item["id"] = key
        item["status"] = status
        products.append(item)
    products.sort(key=lambda p: ({"new": 0, "restock": 1, "normal": 2}[p["status"]], p.get("first_seen") or ""))
    write_json(FEED_FILE, {
        "updated_at": now_iso(),
        "source": SOURCE_NAME,
        "count": len(products),
        "products": products,
    })


def ntfy_publish(title: str, message: str, tags=None, priority=3, click=None) -> None:
    payload = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": message,
        "priority": priority,
        "tags": tags or [],
    }
    if click:
        payload["click"] = click
    try:
        resp = requests.post(NTFY_SERVER, data=json.dumps(payload).encode("utf-8"), timeout=10)
        if resp.status_code >= 300:
            print(f"ntfy 回應異常：{resp.status_code} {resp.text[:200]}")
    except Exception as exc:
        print(f"發送 ntfy 通知失敗：{exc}")


def yen(value) -> str:
    return f"¥{int(value):,}" if value else ""


def event_message(product: dict, extra: str = "") -> str:
    lines = [product["title"]]
    details = " ".join(x for x in (yen(product.get("price")), extra) if x)
    if details:
        lines.append(details)
    lines.append("點我前往 Amazon JP")
    return "\n".join(lines)


def notify_delisted(items: list[dict]) -> None:
    for p in items:
        ntfy_publish(
            "[Amazon JP] 🔻 已消失",
            f"{p.get('title', p.get('key', '未知商品'))}\n已從 Amazon 搜尋結果消失。",
            tags=["arrow_down"],
            priority=2,
            click=p.get("url"),
        )


def send_notifications(new_items, restocks, price_drops, keywords):
    if keywords:
        starred = []
        normal_new = []
        for p in new_items:
            kw = matched_keyword(p["title"], keywords)
            if kw:
                starred.append((p, kw))
            else:
                normal_new.append(p)
        for p, kw in starred:
            ntfy_publish(
                "[Amazon JP] 🔔 關注新商品",
                event_message(p, f"命中「{kw}」"),
                tags=["bell", "star"],
                priority=5,
                click=p["url"],
            )
        new_items = normal_new

    total = len(new_items) + len(restocks) + len(price_drops)
    if total == 0:
        return

    if total > FLOOD_THRESHOLD:
        lines = []
        if new_items:
            lines.append(f"🆕 新出現 {len(new_items)} 項")
            lines.extend(f"- {p['title']}" for p in new_items[:5])
        if restocks:
            lines.append(f"🔁 重新出現 {len(restocks)} 項")
            lines.extend(f"- {p['title']}" for p in restocks[:5])
        if price_drops:
            lines.append(f"📉 降價 {len(price_drops)} 項")
        ntfy_publish("[Amazon JP] Beyblade 大量異動", "\n".join(lines), tags=["bell"], priority=4)
        return

    for p in restocks:
        ntfy_publish("[Amazon JP] 🔁 重新出現", event_message(p), tags=["rotating_light"], priority=5, click=p["url"])
    for p in new_items:
        ntfy_publish("[Amazon JP] 🆕 新出現", event_message(p), tags=["sparkles"], priority=4, click=p["url"])
    for p, old_price in price_drops:
        ntfy_publish(
            "[Amazon JP] 📉 降價",
            event_message(p, f"{yen(old_price)} → {yen(p.get('price'))}"),
            tags=["chart_with_downwards_trend"],
            priority=3,
            click=p["url"],
        )


def main() -> int:
    print("開始檢查 Amazon JP Beyblade X…")
    state, meta = split_meta(read_json(STATE_FILE, {}))
    fail_count = int(meta.get("consecutive_failures", 0) or 0)

    try:
        page_html = download_html()
        products = parse_products(page_html)
    except Exception as exc:
        fail_count += 1
        meta["consecutive_failures"] = fail_count
        meta["last_failure_at"] = now_iso()
        meta["last_error"] = str(exc)
        save_state_with_meta(state, meta)
        print(f"抓取失敗：{exc}（連續第 {fail_count} 次）")
        if fail_count >= FAIL_ALERT_THRESHOLD and (fail_count - FAIL_ALERT_THRESHOLD) % FAIL_ALERT_THRESHOLD == 0:
            ntfy_publish(
                "[Amazon JP] ⚠️ 連續抓取失敗",
                f"已連續 {fail_count} 次無法讀取 Amazon JP 搜尋結果。\n最後錯誤：{exc}",
                tags=["warning"],
                priority=4,
            )
        return 0

    if DEBUG:
        print(json.dumps(products[:3], ensure_ascii=False, indent=2))

    current = {p["key"]: p for p in products}
    if not current:
        save_state_with_meta(state, meta)
        print("沒解析到任何 Amazon 商品。")
        return 0

    if fail_count:
        print(f"抓取成功，連續失敗計數由 {fail_count} 歸零。")
    meta["consecutive_failures"] = 0
    meta.pop("last_error", None)
    meta.pop("last_failure_at", None)

    ts = now_iso()
    append_history(current, ts)

    if not state:
        for p in current.values():
            p["first_seen"] = ts
        save_state_with_meta(current, meta)
        write_feed(current)
        print(f"首次執行：已記錄 {len(current)} 個商品為基準，下次有變動才通知。")
        return 0

    new_items, restocks, price_drops = [], [], []
    for key, p in current.items():
        old = state.get(key)
        if old is None:
            p["first_seen"] = ts
            new_items.append(p)
        else:
            p["first_seen"] = old.get("first_seen", ts)
            if old.get("in_stock") is False and p.get("in_stock") is True:
                restocks.append(p)
            if NOTIFY_PRICE_DROP and old.get("price") and p.get("price") and p["price"] < old["price"]:
                price_drops.append((p, old["price"]))

    delisted = [old for key, old in state.items() if key not in current]
    send_notifications(new_items, restocks, price_drops, load_watchlist())
    notify_delisted(delisted)
    save_state_with_meta(current, meta)
    write_feed(current, [p["key"] for p in new_items], [p["key"] for p in restocks])
    print(f"完成：新出現 {len(new_items)}、重新出現 {len(restocks)}、降價 {len(price_drops)}、消失 {len(delisted)}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
