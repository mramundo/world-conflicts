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

/* ---------- Theme (palette + mode) ----------
   Two orthogonal preferences:
   - palette: visual identity (current | press-room | command-center | midnight-atlas | nordic-dusk)
   - mode:    dark / light
   Both are persisted independently in localStorage so the user's choices
   survive reloads. Legacy `wc-theme` is migrated into `wc-mode`.
*/
const PALETTES = ['current', 'press-room', 'command-center', 'midnight-atlas', 'nordic-dusk'];
const MODES    = ['dark', 'light'];

function initTheme() {
  const root = document.documentElement;

  // --- Read stored prefs, falling back to sensible defaults. ---
  let storedPalette = localStorage.getItem('wc-palette');
  if (!PALETTES.includes(storedPalette)) storedPalette = 'current';

  let storedMode = localStorage.getItem('wc-mode');
  if (!MODES.includes(storedMode)) {
    // Migrate legacy `wc-theme` key if present, otherwise use the system preference.
    const legacy = localStorage.getItem('wc-theme');
    if (MODES.includes(legacy)) {
      storedMode = legacy;
      localStorage.setItem('wc-mode', legacy);
      localStorage.removeItem('wc-theme');
    } else {
      const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
      storedMode = prefersLight ? 'light' : 'dark';
    }
  }

  applyTheme(storedPalette, storedMode);

  // --- Dark / light toggle ---
  $('#themeToggle')?.addEventListener('click', () => {
    const next = root.dataset.mode === 'light' ? 'dark' : 'light';
    applyTheme(root.dataset.palette, next);
    localStorage.setItem('wc-mode', next);
  });

  // --- Palette picker ---
  const toggle = $('#paletteToggle');
  const menu   = $('#paletteMenu');
  if (toggle && menu) {
    const options = [...menu.querySelectorAll('.palette-picker__option')];

    const markCurrent = (palette) => {
      options.forEach(o => o.setAttribute('aria-current',
        o.dataset.palette === palette ? 'true' : 'false'));
    };
    markCurrent(storedPalette);

    const closeMenu = () => {
      menu.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
    };
    const openMenu = () => {
      menu.hidden = false;
      toggle.setAttribute('aria-expanded', 'true');
    };

    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.hidden ? openMenu() : closeMenu();
    });

    options.forEach(opt => {
      opt.addEventListener('click', (e) => {
        e.stopPropagation();
        const palette = opt.dataset.palette;
        if (!PALETTES.includes(palette)) return;
        applyTheme(palette, root.dataset.mode);
        localStorage.setItem('wc-palette', palette);
        markCurrent(palette);
        closeMenu();
      });
    });

    // Dismiss on outside click or Escape.
    document.addEventListener('click', (e) => {
      if (!menu.hidden && !menu.contains(e.target) && e.target !== toggle) closeMenu();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !menu.hidden) closeMenu();
    });
  }
}

function applyTheme(palette, mode) {
  const root = document.documentElement;
  root.dataset.palette = palette;
  root.dataset.mode = mode;
  // Clean up legacy attribute if ever set by an older build.
  if (root.hasAttribute('data-theme')) root.removeAttribute('data-theme');
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
