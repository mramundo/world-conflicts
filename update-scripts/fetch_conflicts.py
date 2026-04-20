#!/usr/bin/env python3
"""
fetch_conflicts.py — Builds data/conflicts.json by combining:

1. a curated base (conflicts.seed.json)
2. freshness updates from the Wikipedia page
   "List of ongoing armed conflicts" — categorized by intensity.

No API key required. Run:
    python update-scripts/fetch_conflicts.py

Dependencies: requests (see requirements.txt).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "conflicts.seed.json"
OUT = ROOT / "data" / "conflicts.json"

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "List_of_ongoing_armed_conflicts"
USER_AGENT = "world-conflicts-bot/1.0 (https://github.com)"
REQUEST_TIMEOUT = 20


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fetch_wiki_summary() -> dict:
    """Fetch the plaintext of the Wikipedia page for a freshness check."""
    try:
        resp = requests.get(
            WIKI_API,
            params={
                "action": "query",
                "prop": "extracts|revisions",
                "explaintext": 1,
                "exsectionformat": "plain",
                "rvprop": "timestamp",
                "titles": WIKI_PAGE,
                "format": "json",
                "redirects": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values())) if pages else {}
        return {
            "extract": page.get("extract", ""),
            "revision": (page.get("revisions") or [{}])[0].get("timestamp"),
        }
    except Exception as exc:
        print(f"[warn] wikipedia fetch failed: {exc}", file=sys.stderr)
        return {}


def enrich_with_wiki(items: list[dict], wiki_text: str) -> list[dict]:
    """Refresh 'lastUpdate' for conflicts still mentioned in the Wikipedia page."""
    if not wiki_text:
        return items
    lower = wiki_text.lower()
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    enriched = []
    for it in items:
        still_mentioned = any(
            re.search(rf"\b{re.escape(c.lower())}\b", lower)
            for c in it.get("countries", [])
        )
        if still_mentioned:
            it = {**it, "lastUpdate": today}
        enriched.append(it)
    return enriched


def main() -> int:
    if not SEED.exists():
        print(f"[err] seed missing: {SEED}", file=sys.stderr)
        return 1

    seed_data = json.loads(SEED.read_text(encoding="utf-8"))
    items = list(seed_data.get("items", []))

    print(f"→ Seed: {len(items)} conflicts")
    print("→ Checking freshness on Wikipedia…")
    wiki = fetch_wiki_summary()
    items = enrich_with_wiki(items, wiki.get("extract", ""))

    output = {
        "updated": now_iso(),
        "source": "curated seed + Wikipedia freshness (List of ongoing armed conflicts)",
        "wikipediaRevision": wiki.get("revision"),
        "items": items,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Wrote {len(items)} conflicts to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
