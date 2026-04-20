/* =========================================================
   World Conflicts — App entry point
   Wires up: theme, data fetch, globe, conflicts list, news.
   Shared selection state keeps globe ↔ list in sync.
   ========================================================= */

import { initGlobe } from './globe.js';
import { initConflictsList } from './conflicts-list.js';
import { initNews } from './news.js';

const $ = (sel, root = document) => root.querySelector(sel);

const CONFIG = {
  conflictsUrl: 'data/conflicts.json',
  newsUrl: 'data/news.json',
  seedConflictsUrl: 'data/conflicts.seed.json',
  seedNewsUrl: 'data/news.seed.json',
};

const LOCALE = 'en-US';

/* ---------- Shared selection state ---------- */
function createStore(initial = {}) {
  const listeners = new Set();
  const state = { ...initial };
  return {
    get: (key) => state[key],
    set(key, val) {
      if (state[key] === val) return;
      state[key] = val;
      listeners.forEach(fn => fn(key, val, state));
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

/* ---------- Theme ---------- */
function initTheme() {
  const saved = localStorage.getItem('wc-theme');
  const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
  const theme = saved ?? (prefersLight ? 'light' : 'dark');
  document.documentElement.dataset.theme = theme;

  $('#themeToggle')?.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('wc-theme', next);
  });
}

/* ---------- Data loading ---------- */
async function fetchJSON(url) {
  try {
    const res = await fetch(url, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`[data] fetch failed for ${url}:`, err.message);
    return null;
  }
}

async function loadData() {
  const [conflicts, news] = await Promise.all([
    fetchJSON(CONFIG.conflictsUrl).then(d => d ?? fetchJSON(CONFIG.seedConflictsUrl)),
    fetchJSON(CONFIG.newsUrl).then(d => d ?? fetchJSON(CONFIG.seedNewsUrl)),
  ]);
  return {
    conflicts: conflicts ?? { updated: null, items: [] },
    news: news ?? { updated: null, items: [] },
  };
}

/* ---------- Formatters ---------- */
const fmtDate = (iso) => {
  if (!iso) return '—';
  try {
    return new Intl.DateTimeFormat(LOCALE, {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    }).format(new Date(iso));
  } catch { return '—'; }
};

/* ---------- Hero monitoring recap (inline numbers) ---------- */
function renderHeroRecap({ conflicts }) {
  const countries = new Set(conflicts.items.flatMap(c => c.countries ?? []));
  animateNumber($('#heroConflicts'), conflicts.items.length);
  animateNumber($('#heroCountries'), countries.size);
}

function animateNumber(el, target) {
  if (!el || !Number.isFinite(target)) return;
  const duration = 700;
  const start = performance.now();
  function step(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = Math.round(target * eased).toLocaleString(LOCALE);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

/* ---------- Footer / header meta ---------- */
function setMeta({ conflicts, news }) {
  const latestUpdate = [conflicts.updated, news.updated]
    .filter(Boolean)
    .sort()
    .pop();
  const txt = latestUpdate ? fmtDate(latestUpdate) : '—';
  $('#lastUpdate').textContent = `Updated ${txt}`;
  $('#footerUpdate').textContent = txt;
  $('#year').textContent = new Date().getFullYear();
}

/* ---------- Boot ---------- */
(async function boot() {
  initTheme();

  const data = await loadData();

  setMeta(data);
  renderHeroRecap(data);

  // Shared selection store: currently-focused conflict id
  const store = createStore({ selectedId: null });

  initGlobe({
    container: '#globe',
    loadingEl: '#globeLoading',
    conflicts: data.conflicts.items,
    store,
  });

  initConflictsList({
    listEl: '#conflictsList',
    countEl: '#conflictsCount',
    emptyEl: '#conflictsEmpty',
    searchEl: '#conflictsSearch',
    filterBtns: '.conflicts-list__filters .mini-chip',
    conflicts: data.conflicts.items,
    store,
  });

  initNews({
    listEl: '#newsList',
    emptyEl: '#newsEmpty',
    filterBtns: '#news-section .filters .chip',
    searchEl: '#newsSearch',
    loadMoreEl: '#loadMore',
    items: data.news.items,
  });
})();
