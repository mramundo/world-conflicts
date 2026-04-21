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

# ----- Strict relevance filtering ---------------------------------------
#
# The old filter let through anything that matched ANY keyword across four
# loose categories — economy + energy + humanitarian + conflict — which
# produced 120+ items/hour including sports, tech and market chatter.
#
# New rule: a headline must be *unambiguously* about an active armed
# conflict, a geopolitical crisis that's fueling one, or the humanitarian /
# diplomatic fallout of one. Everything else is dropped.
#
# Gate model:
#   1. Reject immediately if the headline contains any DENY_KEYWORD
#      (sports, celebrity, lifestyle, generic tech — sources of the
#      accidental NBA / entertainment leaks).
#   2. Score the remaining headline with STRONG_CONFLICT_SIGNALS (hard
#      war/crisis vocabulary) and ACTIVE_CONFLICT_NAMES (proper nouns of
#      today's hotspots). Must clear a minimum threshold to pass.
#   3. Bonus for opinion/analysis pieces — outlets that do
#      context/analysis around a news event get boosted.
#   4. Then keep at most MAX_PER_SOURCE item(s) per outlet, preferring the
#      highest-scored (opinion beats spot news on ties).

# --- Denylist: presence of any of these kills the item outright.
DENY_KEYWORDS: tuple[str, ...] = (
    # Sports
    "nba", "nfl", "mlb", "nhl", "wnba", "ncaa", "mls ",
    "basketball", "baseball", "ice hockey", "tennis", "cricket",
    "rugby", "golf ", "formula 1", "formula one", " f1 ", "motogp",
    "olympics", "olympic games", "world cup", "fifa", "uefa",
    "premier league", "champions league", "super bowl", "playoffs",
    "tournament win", "world series",
    "striker scored", "hat-trick", "own goal",
    " athlete ", "retires from", "signed to club",
    # Entertainment / celebrity / royals
    "celebrity", "celebrities", "hollywood", "grammys", "oscars",
    "oscar-winning", "met gala", "red carpet", "box office",
    "film festival", "tv series", "tv show", "netflix series",
    "taylor swift", "kardashian", "beyoncé",
    "royal family", "king charles", "prince william", "prince harry",
    # Lifestyle / filler
    "travel guide", "recipe", "horoscope", "astrology", "zodiac",
    "dating app", "wellness tips", "fashion week",
    # Consumer tech (not geopolitics)
    "iphone 1", "iphone 2", "galaxy s2", "pixel phone",
    "tesla model", "app review", "game review", "gameplay",
    "new emoji",
)

# --- Strong signals (hard vocabulary of war / crisis / diplomacy).
# Having at least one of these is worth a lot toward the score.
STRONG_CONFLICT_SIGNALS: tuple[str, ...] = (
    "war", "guerra", "warfare", "ceasefire", "cease-fire",
    "cessate il fuoco", "armistice", "peace talks", "peace deal",
    "peace plan", "truce", "tregua",
    "airstrike", "air strike", "air raid", "missile strike",
    "missile attack", "drone strike", "drone attack", "shelling",
    "artillery", "bombed", "bombing", "bomb attack", "car bomb",
    "suicide bomb", "battlefield", "front line", "frontline",
    "offensive", "counteroffensive", "invasion", "invaded",
    "troops", "military forces", "armed forces", "soldiers",
    "combat", "battle", "battaglia", "clash", "clashes", "skirmish",
    "rebel", "rebels", "ribelli", "insurgen", "insorti",
    "militant", "militants", "militia", "paramilitary",
    "hostage", "hostages", "captive", "abducted", "kidnapped",
    "siege", "besieged", "stormed",
    "killed in", "dead in", "wounded in", "casualties",
    "war crime", "war crimes", "atrocity", "atrocities",
    "massacre", "genocide", "ethnic cleansing",
    "refugee", "refugees", "displaced people", "idps",
    "sanctions", "sanzioni",
    "coup", "putsch", "junta",
    "attack on", "strike on", "raid on",
    "terror attack", "terrorist attack", "attentato",
)

# --- Proper nouns for currently active hotspots.
ACTIVE_CONFLICT_NAMES: tuple[str, ...] = (
    "ukraine", "ucraina", "kyiv", "kiev", "donbas", "donetsk",
    "luhansk", "crimea", "mariupol", "kharkiv", "bakhmut",
    "zaporizhzhia", "odesa",
    "russian forces", "russian military", "kremlin", "putin",
    "zelensky", "zelenskyy",
    "gaza", "hamas", "west bank", "idf ", "netanyahu", "rafah",
    "khan younis", "israeli strike", "israeli strikes",
    "hezbollah", "south lebanon", "beirut strike",
    "houthi", "houthis", "red sea attack", "ansar allah",
    "sudan war", "rsf ", "khartoum", "darfur", "sudanese army",
    "myanmar", "tatmadaw",
    "yemen war", "yemeni civil war",
    "syria", "siria", "idlib", "hts ", "syrian transition",
    "eastern congo", "drc conflict", "goma", "m23 ", "kivu",
    "rwandan-backed",
    "sahel", "jnim", "iswap", "boko haram", "mali junta",
    "burkina faso junta", "niger junta",
    "haiti gangs", "port-au-prince",
    "taliban", "kabul", "iskp", "islamic state khorasan",
    "iranian drone", "iranian proxy", "irgc", "revolutionary guard",
    "kashmir", "line of control",
    "farc dissidents", "eln colombia", "clan del golfo",
    "libyan militia", "tripoli clashes", "haftar",
    "tigray", "amhara", "oromia", "fano militia",
    "al-shabaab", "mogadishu",
    "cartel violence", "narco war", "drug cartel",
    "ethnic violence in", "civil war in",
)

# --- Humanitarian / diplomatic signals (boost, not gate).
SOFT_RELEVANCE_SIGNALS: tuple[str, ...] = (
    "humanitarian", "humanitarian crisis", "aid convoy",
    "aid workers", "aid blocked", "famine", "carestia",
    "malnutrition", "starvation",
    "un security council", "security council vote",
    "icc ", "international criminal court", "icj ",
    "war-torn", "conflict zone", "battle-weary",
    "evacuation", "evacuated",
    "foreign minister", "envoy",
    "diplomatic", "diplomacy",
    "asylum", "asylum seekers",
)

# --- Opinion / analysis signals.
# URL path markers that indicate opinion / analysis / commentary sections.
OPINION_URL_MARKERS: tuple[str, ...] = (
    "/opinion/", "/opinions/", "/analysis/", "/commentary/",
    "/commentisfree/", "/editorial/", "/editorials/", "/viewpoint/",
    "/idees/", "/longread/", "/features/", "/perspective/",
    "foreignpolicy.com",      # FP is entirely analysis
    "rferl.org/a/",           # RFE/RL puts features under /a/
    "/comment/",
    "/columns/", "/column/",
)

# Titles that lead with an explicit analysis prefix or a classic
# analysis framing ("Why …", "How …", "What … means for …").
OPINION_TITLE_RE = re.compile(
    r"^\s*("
    r"opinion\b|analysis\b|commentary\b|editorial\b|comment\b|"
    r"explainer\b|perspective\b|profile\b|"
    r"why\s|how\s|what\s|is\s|are\s|can\s|should\s|will\s"
    r")",
    re.I,
)

# --- Scoring / gating thresholds.
STRONG_SIGNAL_WEIGHT = 3
ACTIVE_NAME_WEIGHT = 1
SOFT_SIGNAL_WEIGHT = 1
OPINION_BONUS = 3
# Maximum hits we count per category (prevents "Russia / Russian / Kremlin /
# Putin / Moscow" from stacking a single article to an unfair score).
MAX_HITS_PER_CATEGORY = 3
# Minimum score to even be considered. Calibrated so that a single name
# match alone ("Russia") is NOT enough — must have a verb/noun of war,
# or a name + a secondary signal.
MIN_SCORE = 3

# --- Output caps.
# At most this many articles from the same outlet per run. Keeps one
# publication from flooding the list.
MAX_PER_SOURCE = 1
# Hard cap on total articles in the JSON payload (15 sources × 1 each
# gives at most ~15; leave a little slack in case we ever relax the cap).
MAX_TOTAL = 20
# Drop anything older than this — avoids RSS feeds that occasionally
# surface week-old evergreen analysis.
MAX_AGE_HOURS = 72
REQUEST_TIMEOUT = 20
# og:image fetch: now cheap because we keep only ~15 items total.
MAX_OG_FETCH = 20
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


def _compile_union(terms: tuple[str, ...]) -> re.Pattern:
    """Compile a union-of-alternatives regex with word boundaries, so
    that 'war' doesn't leak into 'warned', 'raid' doesn't leak into
    'afraid', etc. This was how the Le Monde 'Fed chair' item was
    slipping through before."""
    escaped = sorted({re.escape(t.strip().lower()) for t in terms if t.strip()}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.I)


_DENY_RE = _compile_union(DENY_KEYWORDS)
_STRONG_RE = _compile_union(STRONG_CONFLICT_SIGNALS)
_NAMES_RE = _compile_union(ACTIVE_CONFLICT_NAMES)
_SOFT_RE = _compile_union(SOFT_RELEVANCE_SIGNALS)


def _count_unique(text: str, pat: re.Pattern) -> int:
    """Count DISTINCT matching terms, not occurrences — so a headline
    that just hammers 'Russia Russia Russia' doesn't get inflated."""
    matches = {m.lower() for m in pat.findall(text)}
    return min(len(matches), MAX_HITS_PER_CATEGORY)


def _is_opinion(url: str, title: str) -> bool:
    lu = (url or "").lower()
    if any(m in lu for m in OPINION_URL_MARKERS):
        return True
    if OPINION_TITLE_RE.match(title or ""):
        return True
    return False


def _score_item(title: str, desc: str, url: str) -> tuple[int, list[str]]:
    """Return (score, categories). Score of 0 means the item is rejected.
    Categories are for the UI filter chips ('conflict', 'analysis', etc.)."""
    text = f"{title}\n{desc}".lower()

    # 1. Denylist — sports / celebrity / lifestyle kill immediately.
    if _DENY_RE.search(text):
        return 0, []

    strong_hits = _count_unique(text, _STRONG_RE)
    name_hits = _count_unique(text, _NAMES_RE)
    soft_hits = _count_unique(text, _SOFT_RE)
    opinion = _is_opinion(url, title)

    # 2. Substantive-content gate. Opinion framing alone isn't enough
    # — we need actual war vocabulary OR a concrete named hotspot +
    # a secondary signal. A lone "Russia" mention is NOT enough; a
    # "Why X is doomed" analysis that only touches Iran-as-tangent is
    # NOT enough. This is what was letting "Fed chair appointment"
    # pieces through before.
    if strong_hits == 0:
        if name_hits == 0:
            return 0, []
        if name_hits < 2 and soft_hits == 0:
            return 0, []

    # 3. Score
    score = (
        strong_hits * STRONG_SIGNAL_WEIGHT
        + name_hits * ACTIVE_NAME_WEIGHT
        + soft_hits * SOFT_SIGNAL_WEIGHT
        + (OPINION_BONUS if opinion else 0)
    )
    if score < MIN_SCORE:
        return 0, []

    # 4. Categories (used by the UI filter chips).
    cats: list[str] = []
    if strong_hits or name_hits:
        cats.append("conflict")
    if soft_hits:
        cats.append("humanitarian")
    if opinion:
        cats.append("analysis")
    return score, cats


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


def _too_old(pub_iso: str) -> bool:
    """True if the item is older than MAX_AGE_HOURS. Anything we can't
    parse is kept — better to show a dateless item than to drop it."""
    if not pub_iso:
        return False
    try:
        dt = datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
    except Exception:
        return False
    age_s = (datetime.now(tz=timezone.utc) - dt).total_seconds()
    return age_s > MAX_AGE_HOURS * 3600


def fetch_feed(source: str, url: str) -> FeedResult:
    """Fetch and parse a single RSS feed.
    Never raises — errors are attached to the returned FeedResult so the
    caller can log them aggregated and decide what to do.

    After fetching, the best-scored items (up to MAX_PER_SOURCE) are kept
    — preferring opinion/analysis pieces that give context around an
    active crisis over raw spot news."""
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
    scored: list[tuple[int, dict]] = []
    for entry in parsed.entries:
        title = _clean(entry.get("title"))
        desc = _clean(entry.get("summary") or entry.get("description"))
        link = entry.get("link") or ""
        if not title or not link:
            continue
        published = _published(entry)
        if _too_old(published):
            continue

        score, cats = _score_item(title, desc, link)
        if score <= 0:
            continue

        uid = hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]
        scored.append((score, {
            "id": f"{source[:3].lower()}-{uid}",
            "title": title,
            "description": desc[:320] + ("…" if len(desc) > 320 else ""),
            "url": link,
            "source": source,
            "publishedAt": published,
            "image": _first_image(entry),
            "categories": cats,
            "relevanceScore": score,
            "isAnalysis": "analysis" in cats,
            "tags": [],
        }))

    # Keep only the top MAX_PER_SOURCE, preferring score then recency.
    scored.sort(key=lambda pair: (pair[0], pair[1]["publishedAt"]), reverse=True)
    result.items = [it for _, it in scored[:MAX_PER_SOURCE]]

    tag = result.status_tag
    preview = ""
    if result.items:
        top = result.items[0]
        flag = "[analysis] " if top.get("isAnalysis") else ""
        preview = f" — top: {flag}{top['title'][:70]}"
    suffix = f"score={scored[0][0]}" if scored else "no pass"
    if tag == "ok":
        print(f"[ok]    {source}: {len(result.items)}/{result.raw_entries} ({suffix}){preview}")
    else:
        # Non-fatal but worth flagging; these used to pass silently.
        print(f"[{tag}] {source}: {len(result.items)}/{result.raw_entries} ({suffix}){preview}")
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

    # Safety rail: only abort if the whole fetch was a wash — i.e. no
    # feed returned any raw entries at all. Zero items with healthy
    # feeds is now a *legitimate* outcome (the strict filter can
    # genuinely find nothing worth surfacing in a given hour).
    total_raw = sum(r.raw_entries for r in results)
    if total_raw == 0:
        print(
            f"[abort] zero raw entries across {len(results)} feeds — "
            f"treating as outage, leaving {OUT.relative_to(ROOT)} untouched.",
            file=sys.stderr,
        )
        return 2

    output = {
        "updated": now_iso(),
        "source": "Public RSS — international outlets (strict filter)",
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
