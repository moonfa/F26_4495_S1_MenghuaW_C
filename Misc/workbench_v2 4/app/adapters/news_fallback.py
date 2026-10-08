"""News when the OpenBB route returns nothing. Tries several independent routes and reports what each returned,
so an empty result is diagnosable instead of silent."""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def _iso(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, timezone.utc).isoformat()
    return str(v)[:32] if v else None


def _url(c: dict):
    for k in ("canonicalUrl", "clickThroughUrl"):
        if isinstance(c.get(k), dict) and c[k].get("url"):
            return c[k]["url"]
    return c.get("link") or c.get("url")


def parse_yf_news(items, limit: int = 8) -> list[dict]:
    """Handles both yfinance layouts: nested {'content': {...}} and the older flat dicts."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        c = it["content"] if isinstance(it.get("content"), dict) else it
        if not c.get("title"):
            continue
        prov = c.get("provider")
        out.append({"title": str(c["title"]).strip(),
                    "date": _iso(c.get("pubDate") or c.get("displayTime") or c.get("providerPublishTime")),
                    "source": (prov.get("displayName") if isinstance(prov, dict) else None) or c.get("publisher"),
                    "url": _url(c)})
        if len(out) >= limit:
            break
    return out


def parse_rss(xml_text: str, limit: int = 8) -> list[dict]:
    out = []
    for item in ET.fromstring(xml_text).iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        pub = item.findtext("pubDate")
        try:
            date = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat() if pub else None
        except (TypeError, ValueError):
            date = pub
        out.append({"title": title, "date": date, "source": "Yahoo Finance RSS", "url": (item.findtext("link") or "").strip() or None})
        if len(out) >= limit:
            break
    return out


def _rss(symbol: str, limit: int):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return parse_rss(r.read().decode("utf-8", "replace"), limit)


def fetch_news(symbol: str, limit: int = 8) -> tuple[list[dict], str]:
    """Returns (items, note). `note` says which route worked, or what every route returned."""
    notes: list[str] = []
    try:
        import yfinance as yf
        routes = [("Ticker.news", lambda: yf.Ticker(symbol).news),
                  ("Ticker.get_news", lambda: yf.Ticker(symbol).get_news(count=limit)),
                  ("Search", lambda: yf.Search(symbol, news_count=limit).news)]
    except ImportError:
        routes = []
        notes.append("yfinance not installed")
    for name, fn in routes:
        try:
            raw = fn()
            items = parse_yf_news(raw, limit)
            if items:
                return items, f"News from yfinance {name}."
            keys = sorted(raw[0])[:5] if raw and isinstance(raw[0], dict) else ""
            notes.append(f"{name}: {len(raw or [])} raw, 0 usable {keys}".strip())
        except Exception as exc:
            notes.append(f"{name}: {type(exc).__name__} {str(exc)[:60]}")
    try:
        items = _rss(symbol, limit)
        if items:
            return items, "News from Yahoo RSS."
        notes.append("RSS: 0 items")
    except Exception as exc:
        notes.append(f"RSS: {type(exc).__name__} {str(exc)[:60]}")
    return [], "News unavailable. " + "; ".join(notes)
