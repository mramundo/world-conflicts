# World Conflicts

A responsive web + mobile site that shows **active conflicts around the world** on an interactive 3D globe and aggregates the **latest news** from reliable international outlets, with a focus on conflict, economy, energy and humanitarian impact.

Data is refreshed **automatically every hour** via a GitHub Action, with no paid services.

---

## Features

- **Interactive 3D globe** (Globe.gl + Three.js) with a marker for each conflict, color-coded by intensity.
- **Synced side panel**: clicking a conflict on the globe highlights its row in the list and vice-versa. The selected marker switches to a distinctive violet to stand out against the intensity palette.
- **Detail panel** on click (countries involved, estimated casualties, displaced, start year).
- **News feed** with:
  - category filters (Conflict / Economy / Energy / Humanitarian)
  - text search
  - progressive pagination
  - lazy image loading with an `og:image` fallback when the RSS item has no picture
- **Modern UI** with **dark/light** theme, fluid responsive layout, `prefers-reduced-motion` support, accessible focus ring, skip link, ARIA attributes.
- **Hourly update** via GitHub Actions (free): public RSS → `data/news.json`; curated seed + Wikipedia freshness → `data/conflicts.json`.
- **Free deploy** on GitHub Pages.

## Sources used (all public / free)

- **News**: Reuters, BBC, Al Jazeera, Deutsche Welle, The Guardian, France24, ANSA, Kyiv Independent, Times of Israel, UN News, The Moscow Times, Le Monde, Nikkei Asia.
- **Conflicts**: curated list (based on UCDP, ACLED and the Wikipedia page "List of ongoing armed conflicts"), with automatic freshness refresh from Wikipedia.

The constants live in `update-scripts/fetch_news.py` (feeds) and `data/conflicts.seed.json` (curated conflicts): adding or removing sources is trivial.

---

## Project layout

```
world-conflicts/
├── index.html                 # Main page
├── styles/main.css            # Design system (dark/light, responsive)
├── scripts/
│   ├── app.js                 # Entry point, theme, recap, data loader, shared store
│   ├── globe.js               # 3D globe + selection sync
│   ├── conflicts-list.js      # Side list, filters, bi-directional sync
│   └── news.js                # News rows, filters, search, load more
├── data/
│   ├── conflicts.seed.json    # Curated base (fallback)
│   ├── news.seed.json         # Curated base (fallback)
│   ├── conflicts.json         # (generated) refreshed hourly
│   └── news.json              # (generated) refreshed hourly
├── update-scripts/
│   ├── fetch_news.py          # Aggregates RSS → data/news.json
│   ├── fetch_conflicts.py     # Wikipedia freshness → data/conflicts.json
│   └── requirements.txt
├── .github/workflows/
│   ├── update-data.yml        # Hourly cron (top of every hour)
│   └── pages.yml              # Automatic deploy to GitHub Pages
├── assets/favicon.svg
└── README.md
```

---

## Local development

You only need an HTTP server (ES modules require HTTP, not `file://`).

```bash
# Built-in Python
python3 -m http.server 8000
# then open http://localhost:8000
```

To refresh the data locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r update-scripts/requirements.txt

python update-scripts/fetch_news.py
python update-scripts/fetch_conflicts.py
```

If `data/news.json` / `data/conflicts.json` are missing, the site automatically falls back to the `*.seed.json` files.

---

## Deploy on GitHub Pages (free)

1. Create a repo on GitHub and push the code.
2. `Settings → Pages → Build and deployment → Source: GitHub Actions`.
3. The `pages.yml` workflow runs on first push and publishes the site.
4. The `update-data.yml` workflow runs at the top of every hour and commits fresh data (or you can trigger it manually from `Actions → Update data (hourly) → Run workflow`).

## Common customisations

- **Add an RSS source**: append `{"source": "...", "url": "..."}` to `FEEDS` in `fetch_news.py`.
- **Add a conflict**: edit `data/conflicts.seed.json` (needs `lat`/`lng` and `intensity ∈ {low, medium, high}`).
- **Change update cadence**: tweak the `cron` in `.github/workflows/update-data.yml`.
- **Change the palette**: CSS variables live under `:root` and `[data-theme="light"]` in `styles/main.css`.

---

## Notes

- No paid services. No API keys required.
- The site is **static**: no backend, no database. All data is JSON committed to the repo.
- Data is aggregated automatically — for in-depth analysis always consult the original sources.

License: MIT.
