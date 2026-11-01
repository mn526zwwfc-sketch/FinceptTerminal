"""Noticias: agregación RSS + deduplicación + sentimiento (como NewsService).

El terminal agrega decenas de feeds RSS, agrupa duplicados y etiqueta el
sentimiento. Aquí: Yahoo Finance y MarketWatch (sin API key), dedupe por
título normalizado y un léxico financiero sencillo para el sentimiento.
"""

from __future__ import annotations

import asyncio
import email.utils
import html
import re
import time
import xml.etree.ElementTree as ET

import httpx

from .config import settings
from .market.providers import UA

FEEDS = {
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "MarketWatch RT": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
}
SYMBOL_FEED = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"

POS = {"surge", "surges", "soar", "soars", "jump", "jumps", "rally", "rallies", "gain", "gains", "beat", "beats",
       "record", "upgrade", "upgrades", "rise", "rises", "rebound", "strong", "growth", "profit", "bullish", "boost",
       "tops", "outperform", "higher", "sube", "récord"}
NEG = {"fall", "falls", "drop", "drops", "plunge", "plunges", "slump", "slumps", "miss", "misses", "downgrade",
       "downgrades", "cut", "cuts", "loss", "losses", "lawsuit", "probe", "crash", "weak", "bearish", "decline",
       "declines", "lower", "fears", "recession", "layoffs", "tumble", "tumbles", "sinks", "baja"}

_cache: dict[str, tuple[float, list[dict]]] = {}
_client: httpx.AsyncClient | None = None


def sentiment(text: str) -> tuple[str, float]:
    words = re.findall(r"[a-záéíóúñ]+", text.lower())
    score = sum(w in POS for w in words) - sum(w in NEG for w in words)
    norm = max(-1.0, min(1.0, score / 3))
    return ("positive" if score > 0 else "negative" if score < 0 else "neutral"), round(norm, 2)


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()[:90]


def _parse_rss(xml_bytes: bytes, source: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        if not title:
            continue
        link = (it.findtext("link") or "").strip()
        desc = re.sub(r"<[^>]+>", "", html.unescape(it.findtext("description") or "")).strip()
        pub = it.findtext("pubDate")
        try:
            ts = email.utils.parsedate_to_datetime(pub).timestamp() if pub else time.time()
        except (TypeError, ValueError):
            ts = time.time()
        label, score = sentiment(title + " " + desc)
        items.append({"title": title, "link": link, "summary": desc[:400], "source": source, "published": int(ts),
                      "sentiment": label, "sentiment_score": score})
    return items


async def _fetch(url: str) -> bytes | None:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0, headers={"User-Agent": UA}, follow_redirects=True)
    try:
        r = await _client.get(url)
        return r.content if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def _demo_news(symbol: str | None = None) -> list[dict]:
    now = int(time.time())
    base = [
        ("Markets rally as inflation data comes in softer than expected", "positive"),
        ("Tech stocks slump after weak guidance from chipmakers", "negative"),
        ("Central bank holds rates steady, signals patience", "neutral"),
        ("Oil prices jump on supply concerns", "positive"),
        ("Retail sales decline for second straight month", "negative"),
    ]
    tag = f"{symbol}: " if symbol else ""
    return [{"title": tag + t + " [DEMO]", "link": "", "summary": "Titular de demostración (modo sim / sin red).",
             "source": "Fincept Lite demo", "published": now - i * 900, "sentiment": s,
             "sentiment_score": 0.5 if s == "positive" else -0.5 if s == "negative" else 0.0}
            for i, (t, s) in enumerate(base)]


async def top_news(limit: int = 40, query: str | None = None) -> list[dict]:
    if not settings.live:
        items = _demo_news()
    else:
        hit = _cache.get("top")
        if hit and time.time() - hit[0] < 180:
            items = hit[1]
        else:
            blobs = await asyncio.gather(*(_fetch(u) for u in FEEDS.values()))
            items, seen = [], set()
            for (src, _), blob in zip(FEEDS.items(), blobs):
                for it in _parse_rss(blob or b"", src):
                    key = _norm_title(it["title"])
                    if key not in seen:
                        seen.add(key)
                        items.append(it)
            items.sort(key=lambda x: x["published"], reverse=True)
            if not items:
                items = _demo_news()
            _cache["top"] = (time.time(), items)
    if query:
        ql = query.lower()
        items = [i for i in items if ql in i["title"].lower() or ql in i["summary"].lower()]
    return items[:limit]


async def symbol_news(symbol: str, limit: int = 20) -> list[dict]:
    if not settings.live:
        return _demo_news(symbol)[:limit]
    key = f"sym:{symbol}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1][:limit]
    blob = await _fetch(SYMBOL_FEED.format(symbol=symbol))
    items = _parse_rss(blob or b"", "Yahoo Finance") or _demo_news(symbol)
    items.sort(key=lambda x: x["published"], reverse=True)
    _cache[key] = (time.time(), items)
    return items[:limit]
