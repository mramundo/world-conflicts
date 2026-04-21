#!/usr/bin/env python3
"""
fetch_conflicts.py — Build data/conflicts.json by combining:

1. a curated base (conflicts.seed.json) — keeps the list of conflicts the
   site shows and the fallback numbers.
2. live data from the dedicated Wikipedia page of each conflict —
   extracts casualties and displaced figures from the infobox wikitext,
   and picks up the latest revision timestamp as `lastUpdate`.
3. cross-reference with the news feed (data/news.json) — for every
   conflict, count how many current headlines mention the conflict or
   any of its countries. Exposed as `recentNewsCount` so the UI can
   surface the hottest conflicts.

No API key required. Run:
    python update-scripts/fetch_conflicts.py

Dependencies: requests (see requirements.txt).
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "conflicts.seed.json"
NEWS = ROOT / "data" / "news.json"
NEWS_SEED = ROOT / "data" / "news.seed.json"
OUT = ROOT / "data" / "conflicts.json"

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_LIST_PAGE = "List_of_ongoing_armed_conflicts"
USER_AGENT = "world-conflicts-bot/1.0 (https://github.com/mramundo/world-conflicts)"
REQUEST_TIMEOUT = 20
# Be polite with the Wikipedia API — short delay between per-conflict calls.
WIKI_DELAY_S = 0.25


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------- Wikipedia helpers ----------

def wiki_get(params: dict) -> dict:
    """Single call to the MediaWiki Action API with consistent defaults."""
    merged = {"format": "json", "formatversion": 2, "redirects": 1, **params}
    resp = requests.get(
        WIKI_API,
        params=merged,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_list_page_text() -> dict:
    """Plain-text extract of the generic 'ongoing armed conflicts' list.
    Used as a loose freshness signal: if a conflict's country still appears
    in that list, we know it's still considered active."""
    try:
        data = wiki_get({
            "action": "query",
            "prop": "extracts|revisions",
            "explaintext": 1,
            "exsectionformat": "plain",
            "rvprop": "timestamp",
            "titles": WIKI_LIST_PAGE,
        })
        pages = data.get("query", {}).get("pages", []) or []
        page = pages[0] if pages else {}
        return {
            "extract": page.get("extract", "") or "",
            "revision": (page.get("revisions") or [{}])[0].get("timestamp"),
        }
    except Exception as exc:
        print(f"[warn] list page fetch failed: {exc}", file=sys.stderr)
        return {}


def fetch_page_wikitext(title: str) -> tuple[str, str | None]:
    """Return (wikitext, last_revision_timestamp) for a Wikipedia page.
    Falls back to empty string on error so callers can keep seed values."""
    try:
        data = wiki_get({
            "action": "query",
            "prop": "revisions",
            "rvprop": "content|timestamp",
            "rvslots": "main",
            "titles": title,
        })
        pages = data.get("query", {}).get("pages", []) or []
        if not pages:
            return "", None
        revs = (pages[0] or {}).get("revisions", []) or []
        if not revs:
            return "", None
        wikitext = revs[0].get("slots", {}).get("main", {}).get("content", "") or ""
        return wikitext, revs[0].get("timestamp")
    except Exception as exc:
        print(f"[warn] {title}: {exc}", file=sys.stderr)
        return "", None


# ---------- Infobox parsing ----------

# Patterns that tend to carry casualty / displacement numbers in the infobox.
# We scan the whole wikitext (not just the template block) because many
# infoboxes nest transclusions that we don't expand.
_CASUALTY_KEYS = ("casualties", "deaths", "killed", "fatalities", "dead")
_DISPLACED_KEYS = ("displaced", "refugees", "idps", "internally displaced")

# Sanity caps: any scraped number above these bounds is almost certainly an
# artifact (wrong field picked up, OCR-ish glitch, displaced figure mixed
# into the casualty section, etc.). We reject rather than propagate garbage.
_MAX_CASUALTIES = 10_000_000
_MAX_DISPLACED = 100_000_000

# Numbers in this band are almost always years in context — reject them.
_YEAR_MIN, _YEAR_MAX = 1900, 2099

# When a seed (manual) value is present, we only accept the live value if
# it's within this multiplicative range of the seed. Prevents replacing a
# carefully curated 500,000 with a garbage 2,022.
_SANITY_RATIO = 10


def _clean_wikitext_fragment(s: str) -> str:
    """Strip wikilinks, templates and HTML tags from a short fragment,
    leaving plain text so we can regex-extract numbers."""
    # Drop HTML comments
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.DOTALL)
    # Drop references <ref ...>...</ref> and self-closing <ref />
    s = re.sub(r"<ref[^>]*?/>", " ", s, flags=re.I)
    s = re.sub(r"<ref[^>]*>.*?</ref>", " ", s, flags=re.I | re.DOTALL)
    # Drop remaining HTML tags
    s = re.sub(r"<[^>]+>", " ", s)
    # Collapse simple templates {{...}} (non-nested) to their last piped argument
    for _ in range(3):
        s = re.sub(r"\{\{[^{}]*?\|([^{}|]*?)\}\}", r"\1", s)
    s = re.sub(r"\{\{[^{}]*?\}\}", " ", s)
    # Wikilinks [[a|b]] → b, [[a]] → a
    s = re.sub(r"\[\[[^\]|]*?\|([^\]]*?)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*?)\]\]", r"\1", s)
    return s


_NUMBER_RE = re.compile(
    r"(?<![\d.])("
    r"\d{1,3}(?:[,\u202F\u00A0\s]\d{3})+"   # grouped like "1,234,567" or "1 234 567"
    r"|\d{4,10}"                               # bare integers of a reasonable size
    r")(?![\d.])"
)


def _parse_number(tok: str) -> int | None:
    digits = re.sub(r"[^\d]", "", tok)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def extract_numbers(fragment: str) -> list[int]:
    """Return all plausible integer values appearing in a cleaned fragment."""
    cleaned = _clean_wikitext_fragment(fragment)
    vals: list[int] = []
    for m in _NUMBER_RE.finditer(cleaned):
        n = _parse_number(m.group(1))
        if n is not None:
            vals.append(n)
    return vals


def _harvest_lines(wikitext: str, keys: tuple[str, ...]) -> list[str]:
    """Return every infobox-style line (starts with `|`) whose parameter
    name matches one of the keys. We match on the left of `=` only."""
    results: list[str] = []
    for raw in wikitext.splitlines():
        if not raw.lstrip().startswith("|"):
            continue
        if "=" not in raw:
            continue
        key_part, _, value_part = raw.partition("=")
        param = re.sub(r"[^a-z]", "", key_part.lower())
        if any(k.replace(" ", "") in param for k in keys):
            results.append(value_part.strip())
    return results


def _plausible(n: int, floor: int, ceiling: int) -> bool:
    """A number is plausible if it's in range AND doesn't look like a year."""
    if n < floor or n > ceiling:
        return False
    if _YEAR_MIN <= n <= _YEAR_MAX:
        return False
    return True


def infobox_max(
    wikitext: str,
    keys: tuple[str, ...],
    floor: int,
    ceiling: int,
) -> int | None:
    """Scan infobox lines matching `keys`, extract numbers, return the
    largest plausible one within [floor, ceiling] that isn't a year.
    None if nothing credible found."""
    if not wikitext:
        return None
    best: int | None = None
    # Give priority to infobox-style lines; if none matched, fall back to a
    # broader sweep of the first ~8000 chars (infobox zone).
    for fragment in _harvest_lines(wikitext, keys):
        for n in extract_numbers(fragment):
            if _plausible(n, floor, ceiling) and (best is None or n > best):
                best = n
    if best is None:
        head = wikitext[:8000]
        for key in keys:
            for m in re.finditer(
                rf"([^\n]{{0,160}}\b{re.escape(key)}\b[^\n]{{0,160}})",
                head,
                flags=re.I,
            ):
                for n in extract_numbers(m.group(1)):
                    if _plausible(n, floor, ceiling) and (best is None or n > best):
                        best = n
    return best


def _within_sanity_range(seed_value: int | float | None, live_value: int) -> bool:
    """Accept live_value only if it's within _SANITY_RATIO× of the seed.
    If the seed is absent or zero, any plausible live value passes."""
    try:
        seed_num = float(seed_value) if seed_value is not None else 0
    except (TypeError, ValueError):
        seed_num = 0
    if seed_num <= 0:
        return True
    lo = seed_num / _SANITY_RATIO
    hi = seed_num * _SANITY_RATIO
    return lo <= live_value <= hi


# ---------- News cross-reference ----------

def load_news_items() -> list[dict]:
    """Prefer the freshly generated news.json; fall back to the seed."""
    for candidate in (NEWS, NEWS_SEED):
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return list(data.get("items", []))
            except Exception as exc:
                print(f"[warn] cannot read {candidate.name}: {exc}", file=sys.stderr)
    return []


def build_news_haystack(items: list[dict]) -> list[str]:
    """Pre-lowercase concatenation of searchable fields for each news item."""
    bags = []
    for it in items:
        parts = [
            it.get("title", ""),
            it.get("description", ""),
            " ".join(it.get("tags", []) or []),
        ]
        bags.append(" ".join(parts).lower())
    return bags


def count_mentions(conflict: dict, haystacks: list[str]) -> int:
    """Count how many news items mention the conflict name or any of its
    countries. Uses whole-word-ish boundaries to avoid false positives."""
    needles: list[str] = []
    name = (conflict.get("name") or "").lower()
    if name:
        # Match the first meaningful word of the name (e.g. "russia", "gaza").
        head = re.split(r"[\s\-–—/,]", name, maxsplit=1)[0]
        if len(head) >= 4:
            needles.append(head)
    for country in conflict.get("countries", []) or []:
        c = country.lower().strip()
        if len(c) >= 4:
            needles.append(c)
    needles = list(dict.fromkeys(needles))  # unique, preserve order
    if not needles:
        return 0
    count = 0
    for bag in haystacks:
        if any(re.search(rf"\b{re.escape(n)}\b", bag) for n in needles):
            count += 1
    return count


# ---------- Main ----------

def enrich_conflict(conflict: dict, list_page_text_lower: str) -> dict:
    """Attach live fields to a conflict based on Wikipedia data."""
    enriched = {**conflict}
    page = conflict.get("wikipediaPage")
    if page:
        wikitext, rev_ts = fetch_page_wikitext(page)
        time.sleep(WIKI_DELAY_S)
        if wikitext:
            casualties_live = infobox_max(
                wikitext, _CASUALTY_KEYS, floor=100, ceiling=_MAX_CASUALTIES
            )
            displaced_live = infobox_max(
                wikitext, _DISPLACED_KEYS, floor=100, ceiling=_MAX_DISPLACED
            )
            # Only replace seed numbers when the live scrape is in a sane
            # range of the curated baseline — prevents a garbage infobox
            # match from poisoning good data.
            if casualties_live and _within_sanity_range(
                conflict.get("casualties"), casualties_live
            ):
                enriched["casualties"] = casualties_live
                enriched["casualtiesSource"] = "wikipedia"
            if displaced_live and _within_sanity_range(
                conflict.get("displaced"), displaced_live
            ):
                enriched["displaced"] = displaced_live
                enriched["displacedSource"] = "wikipedia"
            if rev_ts:
                # Wikipedia revision timestamp like 2026-04-19T12:34:56Z
                enriched["lastUpdate"] = rev_ts[:10]
                enriched["wikipediaRevision"] = rev_ts

    # Fallback freshness: if any of the conflict's countries still appears
    # in the generic list page, bump lastUpdate to today.
    if list_page_text_lower:
        still_listed = any(
            re.search(rf"\b{re.escape((c or '').lower())}\b", list_page_text_lower)
            for c in conflict.get("countries", []) or []
        )
        if still_listed and "lastUpdate" not in enriched:
            enriched["lastUpdate"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return enriched


def main() -> int:
    if not SEED.exists():
        print(f"[err] seed missing: {SEED}", file=sys.stderr)
        return 1

    seed_data = json.loads(SEED.read_text(encoding="utf-8"))
    items = list(seed_data.get("items", []))
    print(f"→ Seed: {len(items)} conflicts")

    print("→ Fetching list-page freshness signal…")
    list_page = fetch_list_page_text()
    list_text_lower = list_page.get("extract", "").lower()

    news_items = load_news_items()
    haystacks = build_news_haystack(news_items)
    print(f"→ News cross-reference: {len(news_items)} recent items loaded")

    print("→ Scraping conflict-specific Wikipedia pages…")
    enriched: list[dict] = []
    for i, c in enumerate(items, start=1):
        e = enrich_conflict(c, list_text_lower)
        e["recentNewsCount"] = count_mentions(e, haystacks)
        marker = "✓" if e.get("casualtiesSource") == "wikipedia" or e.get("displacedSource") == "wikipedia" else "·"
        print(
            f"  {marker} [{i:>2}/{len(items)}] {e.get('name','?'):<36} "
            f"casualties={e.get('casualties'):>8}  "
            f"displaced={e.get('displaced'):>9}  "
            f"news={e['recentNewsCount']:>2}"
        )
        enriched.append(e)

    output = {
        "updated": now_iso(),
        "source": "curated seed + live Wikipedia infobox scrape + news cross-reference",
        "wikipediaListRevision": list_page.get("revision"),
        "items": enriched,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Wrote {len(enriched)} conflicts to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
