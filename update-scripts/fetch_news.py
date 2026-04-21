#!/usr/bin/env python3
"""
fetch_news.py — Aggregates public RSS feeds from international outlets
into a single JSON consumed by the site.

No API key required. Run:
    python update-scripts/fetch_news.py

Dependencies: feedparser, requests (see requirements.txt).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "news.json"

# Feeds chosen for geographical coverage and reliability.
# Mix of Western, Arabic, Asian, African and Latin-American outlets.
FEEDS: list[dict] = [
    {"source": "BBC",              "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"source": "Al Jazeera",       "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"source": "Deutsche Welle",   "url": "https://rss.dw.com/rdf/rss-en-world"},
    {"source": "The Guardian",     "url": "https://www.theguardian.com/world/rss"},
    {"source": "France24",         "url": "https://www.france24.com/en/rss"},
    {"source": "ANSA",             "url": "https://www.ansa.it/sito/notizie/mondo/mondo_rss.xml"},
    {"source": "Kyiv Post",        "url": "https://kyivpost.com/feed"},
    {"source": "Times of Israel",  "url": "https://www.timesofisrael.com/feed/"},
    {"source": "UN News",          "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml"},
    {"source": "The Moscow Times", "url": "https://www.themoscowtimes.com/rss/news"},
    {"source": "Le Monde (EN)",    "url": "https://www.lemonde.fr/en/rss/une.xml"},
    {"source": "Nikkei Asia",      "url": "https://asia.nikkei.com/rss/feed/nar"},
    {"source": "RFE/RL",           "url": "https://www.rferl.org/api/epiqq"},
    {"source": "NPR World",        "url": "https://feeds.npr.org/1004/rss.xml"},
    {"source": "CS Monitor",       "url": "https://rss.csmonitor.com/feeds/world"},
]

# Relevance filters: keywords -> categories.
KEYWORDS: dict[str, list[str]] = {
    "conflict": [
        "war", "guerra", "conflict", "conflitto", "strike", "attacco", "raid",
        "military", "militare", "ceasefire", "cessate il fuoco", "battle", "battaglia",
        "troops", "truppe", "rebel", "ribell", "insurgen", "insorti", "airstrike",
        "drone strike", "front line", "frontline", "fronte", "occupied", "occupata",
        "ukraine", "ucraina", "russia", "gaza", "israel", "israele", "hamas", "hezbollah",
        "houthi", "sudan", "myanmar", "yemen", "syria", "siria", "congo", "rdc",
        "sahel", "mali", "burkina", "niger", "haiti", "afghanistan", "iran", "lebanon",
        "libano", "kashmir", "colombia", "somalia",
    ],
    "economy": [
        "inflation", "inflazione", "gdp", "pil", "recession", "recessione",
        "market", "mercati", "stocks", "borsa", "bond", "yields", "rendimenti",
        "dollar", "euro", "trade", "commercio", "tariff", "dazi", "supply chain",
        "shipping", "noli", "logistics", "logistica",
        "commodity", "commodities", "grain", "grano", "wheat", "corn", "mais",
        "oil", "petrolio", "brent", "wti", "gas", "ttf", "lng",
    ],
    "energy": [
        "oil", "petrolio", "brent", "wti", "gas", "lng", "opec", "ttf",
        "pipeline", "nord stream", "gasdotto", "oleodotto", "energy", "energia",
        "electricity", "elettricità", "renewable", "rinnovabil",
    ],
    "humanitarian": [
        "humanitarian", "umanitario", "refugee", "rifugiato", "displaced", "sfollati",
        "famine", "carestia", "aid", "aiuti", "un ", "onu", "unicef", "wfp", "ocha",
        "civilian", "civili", "hospital", "ospedale", "children", "bambini",
        "malnutrition", "malnutrizione", "crisis", "crisi",
    ],
}

# Hourly cadence: cap the total number of articles to keep the payload lean.
MAX_TOTAL = 120
REQUEST_TIMEOUT = 20
# Max number of articles for which to attempt an og:image fetch when the feed
# doesn't already carry an image. Kept small to stay fast.
MAX_OG_FETCH = 40
USER_AGENT = "world-conflicts-bot/1.0 (+https://github.com)"


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    # Strip simple HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _categorize(title: str, desc: str) -> list[str]:
    text = f"{title} {desc}".lower()
    cats: list[str] = []
    for cat, words in KEYWORDS.items():
        if any(w in text for w in words):
            cats.append(cat)
    return cats


def _relevant(title: str, desc: str) -> bool:
    # Keep only articles that match at least one category.
    return bool(_categorize(title, desc))


def _first_image(entry) -> str | None:
    """Fast image extraction from the feed payload — no HTTP calls."""
    # 1. media:content / media:thumbnail (MRSS)
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key) or []
        for m in media:
            url = m.get("url") if isinstance(m, dict) else None
            if url:
                return url
    # 2. enclosures
    for e in entry.get("enclosures", []) or []:
        if e.get("type", "").startswith("image/") and e.get("href"):
            return e["href"]
    # 3. links with type image/*
    for link in entry.get("links", []) or []:
        if isinstance(link, dict) and link.get("type", "").startswith("image/") and link.get("href"):
            return link["href"]
    # 4. <img> inside summary / content:encoded
    candidates: list[str] = []
    summary = entry.get("summary", "") or ""
    candidates.append(summary)
    for c in entry.get("content", []) or []:
        val = c.get("value") if isinstance(c, dict) else None
        if val:
            candidates.append(val)
    for html in candidates:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
        if m:
            return m.group(1)
    # 5. itunes/image-style fallback
    img = entry.get("image", {}) or {}
    if isinstance(img, dict) and img.get("href"):
        return img["href"]
    return None


_OG_PATTERNS = (
    re.compile(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
)

def _fetch_og_image(url: str) -> str | None:
    """Download the first KB of the article page looking for og:image /
    twitter:image. Fails silently — images are a nice-to-have."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Range": "bytes=0-65535"},
            timeout=8,
            stream=True,
        )
        if resp.status_code >= 400:
            return None
        html = resp.text[:65536]
        for pat in _OG_PATTERNS:
            m = pat.search(html)
            if m:
                return m.group(1)
    except Exception:
        return None
    return None


def _published(entry) -> str:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            except Exception:
                pass
    return now_iso()


class FeedResult:
    """Per-feed outcome so main() can print a readable summary and decide
    whether the run is healthy enough to overwrite the previous JSON."""

    __slots__ = ("source", "items", "error", "raw_entries")

    def __init__(self, source: str):
        self.source = source
        self.items: list[dict] = []
        self.error: str | None = None
        self.raw_entries: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def status_tag(self) -> str:
        if self.error:
            return "fail"
        if self.raw_entries == 0:
            return "empty"  # server reachable but returned nothing parseable
        if not self.items:
            return "no-match"  # parsed entries, but none matched our keywords
        return "ok"


def fetch_feed(source: str, url: str) -> FeedResult:
    """Fetch and parse a single RSS feed.
    Never raises — errors are attached to the returned FeedResult so the
    caller can log them aggregated and decide what to do."""
    result = FeedResult(source)
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        print(f"[fail] {source}: {result.error}", file=sys.stderr)
        return result

    result.raw_entries = len(parsed.entries or [])
    for entry in parsed.entries:
        title = _clean(entry.get("title"))
        desc = _clean(entry.get("summary") or entry.get("description"))
        if not title or not entry.get("link"):
            continue
        if not _relevant(title, desc):
            continue

        cats = _categorize(title, desc)
        uid = hashlib.sha1(entry["link"].encode("utf-8")).hexdigest()[:12]

        result.items.append({
            "id": f"{source[:3].lower()}-{uid}",
            "title": title,
            "description": desc[:320] + ("…" if len(desc) > 320 else ""),
            "url": entry["link"],
            "source": source,
            "publishedAt": _published(entry),
            "image": _first_image(entry),
            "categories": cats,
            "tags": [],
        })

    tag = result.status_tag
    if tag == "ok":
        print(f"[ok]    {source}: {len(result.items)} relevant (of {result.raw_entries} entries)")
    else:
        # Non-fatal but worth flagging; these used to pass silently.
        print(f"[{tag}] {source}: {len(result.items)} relevant (of {result.raw_entries} entries)")
    return result


def main() -> int:
    print(f"→ RSS aggregation ({len(FEEDS)} sources)…")
    results: list[FeedResult] = [fetch_feed(f["source"], f["url"]) for f in FEEDS]
    all_items: list[dict] = [item for r in results for item in r.items]

    # De-dup by URL
    seen: set[str] = set()
    deduped: list[dict] = []
    for it in all_items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        deduped.append(it)

    # Sort by published date (desc) and cap
    deduped.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    deduped = deduped[:MAX_TOTAL]

    # Fallback: for the first N articles without an image, try og:image
    missing = [it for it in deduped if not it.get("image")]
    to_fetch = missing[:MAX_OG_FETCH]
    if to_fetch:
        print(f"→ Fetching og:image for {len(to_fetch)} articles without images…")
        for it in to_fetch:
            img = _fetch_og_image(it["url"])
            if img:
                it["image"] = img

    # Aggregate summary — a single line so GitHub Actions logs are easy
    # to skim and so silent degradation shows up clearly in the diff.
    ok_count = sum(1 for r in results if r.ok and r.items)
    fail_count = sum(1 for r in results if not r.ok)
    empty_count = sum(1 for r in results if r.ok and not r.items)
    fail_list = ", ".join(r.source for r in results if not r.ok) or "none"
    print(
        f"SUMMARY: {ok_count}/{len(results)} feeds produced items, "
        f"{empty_count} empty, {fail_count} failed "
        f"({fail_list}); {len(deduped)} unique articles"
    )

    # Safety rail: if the whole run produced zero items and there's an
    # existing news.json, keep the old one rather than clobbering good
    # data with a blank payload — and exit non-zero so the workflow logs
    # flag it for attention.
    if not deduped and OUT.exists():
        print(
            f"[abort] zero items from {len(results)} feeds — keeping existing "
            f"{OUT.relative_to(ROOT)} untouched.",
            file=sys.stderr,
        )
        return 2

    output = {
        "updated": now_iso(),
        "source": "Public RSS — international outlets",
        "feedsOk": ok_count,
        "feedsTotal": len(results),
        "items": deduped,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Wrote {len(deduped)} articles to {OUT.relative_to(ROOT)}")

    # Half of all feeds down → probably an outage on our side worth noticing.
    if fail_count > len(results) / 2:
        print(
            f"[warn] {fail_count}/{len(results)} feeds failed — investigate.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
