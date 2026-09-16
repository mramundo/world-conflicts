/* =========================================================
   Globe — 3D interactive globe via globe.gl (Three.js).
   Integrates with a shared selection store for bi-directional
   sync with the side list.
   ========================================================= */

const $ = (sel, root = document) => root.querySelector(sel);

// Intensity hues are overwritten in initGlobe from the --intensity-* tokens
// in main.css so the globe, legend and list always agree. Hex = fallback.
const INTENSITY_COLOR = { low: '#4ea8ff', medium: '#ffb347', high: '#ff5a5f' };
const INTENSITY_LABEL = { low: 'Low', medium: 'Medium', high: 'High' };
const INTENSITY_SIZE = { low: 0.35, medium: 0.6, high: 0.95 };

// Violet — chosen to stand out against the three intensity hues
// (matches the dark-mode --selected token; kept bright on both textures).
const SELECTED_COLOR = '#a78bfa';

const GLOBE_TEXTURE = {
  dark:  'https://unpkg.com/three-globe@2.31.0/example/img/earth-night.jpg',
  light: 'https://unpkg.com/three-globe@2.31.0/example/img/earth-blue-marble.jpg',
};

// World-atlas TopoJSON — 110m resolution, fast & light (~100KB).
const COUNTRIES_URL = 'https://unpkg.com/world-atlas@2/countries-110m.json';

let globe = null;
let autoRotate = true;

export function initGlobe({ container, loadingEl, conflicts, store }) {
  const el = typeof container === 'string' ? $(container) : container;
  if (!el || typeof window.Globe === 'undefined') {
    console.error('[globe] Globe.gl not loaded');
    return;
  }

  const tokens = getComputedStyle(document.documentElement);
  for (const level of Object.keys(INTENSITY_COLOR)) {
    INTENSITY_COLOR[level] = tokens.getPropertyValue(`--intensity-${level}`).trim() || INTENSITY_COLOR[level];
  }

  // Which countries are currently affected by a conflict — used to highlight
  // their borders and emphasise the label on hover.
  const conflictCountries = new Set(
    conflicts.flatMap(c => (c.countries ?? []).map(name => name.toLowerCase()))
  );

  globe = Globe()(el)
    .backgroundColor('rgba(0,0,0,0)')
    .bumpImageUrl('https://unpkg.com/three-globe@2.31.0/example/img/earth-topology.png')
    .atmosphereAltitude(0.22)
    .showGraticules(false)
    // Country polygons: subtle fill + stronger borders for conflict countries.
    // Labels show on hover via polygonLabel.
    .polygonsData([])   // filled async below once TopoJSON is fetched
    .polygonSideColor(() => 'rgba(0, 0, 0, 0)')
    .polygonAltitude(d => conflictCountries.has(d.properties.name.toLowerCase()) ? 0.008 : 0.004)
    .polygonLabel(d => polygonLabelHtml(d, conflictCountries))
    .pointsData(conflicts)
    .pointLat('lat')
    .pointLng('lng')
    .pointColor(d => resolveColor(d, store))
    .pointAltitude(d => resolveAltitude(d, store))
    .pointRadius(d => resolveRadius(d, store))
    .pointLabel(d => htmlTooltip(d))
    .pointsMerge(false)
    .pointsTransitionDuration(400)
    .onPointClick(d => {
      store?.set('selectedId', d.id);
    });

  // Fetch country borders lazily — doesn't block initial paint.
  loadCountries()
    .then(features => globe?.polygonsData(features))
    .catch(err => console.warn('[globe] countries fetch failed:', err));

  updateRings(conflicts, store);

  // Responsive sizing
  const resize = () => {
    const { clientWidth, clientHeight } = el;
    globe.width(clientWidth).height(clientHeight);
  };
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(el);

  // Initial view + auto-rotate
  globe.controls().autoRotate = true;
  globe.controls().autoRotateSpeed = 0.35;
  globe.controls().enableDamping = true;
  globe.controls().dampingFactor = 0.08;
  globe.pointOfView({ lat: 25, lng: 15, altitude: 2.2 }, 0);

  // Hide loading overlay
  requestAnimationFrame(() => {
    const l = typeof loadingEl === 'string' ? $(loadingEl) : loadingEl;
    l?.classList.add('hidden');
    setTimeout(() => { if (l) l.style.display = 'none'; }, 500);
  });

  // Controls
  $('#resetView')?.addEventListener('click', () => {
    globe.pointOfView({ lat: 25, lng: 15, altitude: 2.2 }, 1200);
    store?.set('selectedId', null);
  });

  const toggleBtn = $('#toggleRotate');
  toggleBtn?.addEventListener('click', () => {
    autoRotate = !autoRotate;
    globe.controls().autoRotate = autoRotate;
    toggleBtn.innerHTML = autoRotate
      ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>'
      : '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="6 4 20 12 6 20 6 4"/></svg>';
    toggleBtn.title = autoRotate ? 'Pause rotation' : 'Resume rotation';
    toggleBtn.setAttribute('aria-label', toggleBtn.title);
  });

  // Pause rotation on user interaction
  const pauseOnInteract = () => {
    if (!autoRotate) return;
    globe.controls().autoRotate = false;
    setTimeout(() => { if (autoRotate) globe.controls().autoRotate = true; }, 6000);
  };
  el.addEventListener('pointerdown', pauseOnInteract);
  el.addEventListener('wheel', pauseOnInteract, { passive: true });

  // Theme: applied now and whenever data-mode actually flips. applyTheme in
  // app.js rewrites data-mode on every palette change too, so skip no-ops
  // instead of re-uploading the globe texture.
  let appliedDark = null;
  const applyGlobeTheme = () => {
    const isDark = document.documentElement.dataset.mode !== 'light';
    if (isDark === appliedDark) return;
    appliedDark = isDark;
    globe
      .globeImageUrl(isDark ? GLOBE_TEXTURE.dark : GLOBE_TEXTURE.light)
      .atmosphereColor(isDark ? '#4ea8ff' : '#6aaef0')
      .polygonCapColor(d => polygonCapColor(d, conflictCountries, isDark))
      .polygonStrokeColor(d => polygonStrokeColor(d, conflictCountries, isDark));
  };
  applyGlobeTheme();
  new MutationObserver(applyGlobeTheme)
    .observe(document.documentElement, { attributes: true, attributeFilter: ['data-mode'] });

  // Selection sync: listen to store → refresh visuals + focus globe
  store?.subscribe((key, val) => {
    if (key !== 'selectedId') return;

    globe.pointColor(d => resolveColor(d, store));
    globe.pointAltitude(d => resolveAltitude(d, store));
    globe.pointRadius(d => resolveRadius(d, store));

    updateRings(conflicts, store);

    if (val) {
      const target = conflicts.find(c => c.id === val);
      if (target) {
        globe.controls().autoRotate = false;
        globe.pointOfView({ lat: target.lat, lng: target.lng, altitude: 1.5 }, 1100);
        setTimeout(() => {
          if (autoRotate) globe.controls().autoRotate = true;
        }, 5000);
      }
    }
  });
}

/* ---------- point visual resolvers ---------- */
function resolveColor(d, store) {
  return store?.get('selectedId') === d.id
    ? SELECTED_COLOR
    : (INTENSITY_COLOR[d.intensity] ?? INTENSITY_COLOR.medium);
}
function resolveAltitude(d, store) {
  const base = 0.01 + INTENSITY_SIZE[d.intensity] * 0.12;
  return store?.get('selectedId') === d.id ? base + 0.08 : base;
}
function resolveRadius(d, store) {
  const base = 0.25 + INTENSITY_SIZE[d.intensity] * 0.35;
  return store?.get('selectedId') === d.id ? base * 1.45 : base;
}

/* Rings: always on high-intensity, plus a distinctive ring on the selected one. */
function updateRings(conflicts, store) {
  if (!globe) return;
  const selectedId = store?.get('selectedId');
  const rings = [];
  conflicts.forEach(c => {
    if (c.intensity === 'high') rings.push({ ...c, _kind: 'intensity' });
    if (c.id === selectedId) rings.push({ ...c, _kind: 'selected' });
  });
  globe
    .ringsData(rings)
    .ringLat('lat').ringLng('lng')
    .ringColor(d => t => withAlpha(d._kind === 'selected' ? SELECTED_COLOR : INTENSITY_COLOR.high, 1 - t))
    .ringMaxRadius(d => d._kind === 'selected' ? 6 : 4)
    .ringPropagationSpeed(d => d._kind === 'selected' ? 3 : 2)
    .ringRepeatPeriod(d => d._kind === 'selected' ? 1100 : 1600);
}

/* Tooltips are styled by .globe-tooltip* in main.css; --tone drives the
   border and tag tint, same mechanism as the list labels. */
function htmlTooltip(d) {
  const color = INTENSITY_COLOR[d.intensity] ?? INTENSITY_COLOR.medium;
  const label = INTENSITY_LABEL[d.intensity] ?? '—';
  const news = Number(d.recentNewsCount ?? 0);
  const newsTag = news > 0
    ? `<span class="globe-tooltip__tag globe-tooltip__tag--muted">${news} recent ${news === 1 ? 'headline' : 'headlines'}</span>`
    : '';
  return `
    <div class="globe-tooltip" style="--tone:${color}">
      <div class="globe-tooltip__title">${escapeHtml(d.name)}</div>
      <div class="globe-tooltip__meta">${escapeHtml((d.countries ?? []).join(', '))}</div>
      <div class="globe-tooltip__tags">
        <span class="globe-tooltip__tag">${label} intensity</span>
        ${newsTag}
      </div>
    </div>
  `;
}

// '#rrggbb' + alpha → 'rgba(…)' (globe.gl colour accessors don't take color-mix).
function withAlpha(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

/* ---------- Country polygons ---------- */

// Subset of Natural Earth names that differ from the seed's `countries` entries.
// Key = Natural Earth polygon name, value = normalised name used in the seed.
const COUNTRY_NAME_ALIASES = {
  'dem. rep. congo':        'democratic republic of the congo',
  'central african rep.':   'central african republic',
  'united states of america': 'united states',
  "côte d'ivoire":          'ivory coast',
  'w. sahara':              'western sahara',
  'bosnia and herz.':       'bosnia and herzegovina',
};

function normaliseCountryName(name) {
  const lower = String(name ?? '').toLowerCase().trim();
  return COUNTRY_NAME_ALIASES[lower] ?? lower;
}

async function loadCountries() {
  if (typeof window.topojson === 'undefined') {
    console.warn('[globe] topojson-client not loaded');
    return [];
  }
  const res = await fetch(COUNTRIES_URL);
  const topo = await res.json();
  const fc = window.topojson.feature(topo, topo.objects.countries);
  return fc.features ?? [];
}

function polygonCapColor(d, conflictCountries, isDark) {
  const name = normaliseCountryName(d.properties?.name);
  const affected = conflictCountries.has(name);
  if (isDark) {
    return affected
      ? withAlpha(INTENSITY_COLOR.high, 0.18) // tint countries with conflicts
      : 'rgba(78, 168, 255, 0.05)';           // near-transparent over the textured globe
  }
  return affected
    ? withAlpha(INTENSITY_COLOR.high, 0.14)
    : 'rgba(15, 20, 35, 0.04)';
}

function polygonStrokeColor(d, conflictCountries, isDark) {
  const name = normaliseCountryName(d.properties?.name);
  const affected = conflictCountries.has(name);
  if (isDark) {
    return affected
      ? 'rgba(255, 180, 180, 0.55)'   // stronger stroke on conflict countries
      : 'rgba(255, 255, 255, 0.18)';
  }
  return affected
    ? 'rgba(140, 20, 40, 0.55)'
    : 'rgba(15, 20, 35, 0.20)';
}

function polygonLabelHtml(d, conflictCountries) {
  const rawName = d.properties?.name ?? '—';
  const norm = normaliseCountryName(rawName);
  const affected = conflictCountries.has(norm);
  const accent = affected ? INTENSITY_COLOR.high : '#6aaef0';
  const tagHtml = affected
    ? `<div class="globe-tooltip__tags"><span class="globe-tooltip__tag">active conflict</span></div>`
    : '';
  return `
    <div class="globe-tooltip" style="--tone:${accent}">
      <div class="globe-tooltip__title">${escapeHtml(rawName)}</div>
      ${tagHtml}
    </div>
  `;
}
