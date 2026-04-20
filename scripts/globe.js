/* =========================================================
   Globe — 3D interactive globe via globe.gl (Three.js).
   Integrates with a shared selection store for bi-directional
   sync with the side list.
   ========================================================= */

const $ = (sel, root = document) => root.querySelector(sel);

const INTENSITY_COLOR = {
  low:    '#4ea8ff',   // blue
  medium: '#ffb347',   // orange
  high:   '#ff5a5f',   // red
};
const INTENSITY_LABEL = { low: 'Low', medium: 'Medium', high: 'High' };
const INTENSITY_SIZE = { low: 0.35, medium: 0.6, high: 0.95 };

// Violet — chosen to stand out against the three intensity hues
const SELECTED_COLOR = '#a78bfa';

let globe = null;
let autoRotate = true;

export function initGlobe({ container, loadingEl, conflicts, store }) {
  const el = typeof container === 'string' ? $(container) : container;
  if (!el || typeof window.Globe === 'undefined') {
    console.error('[globe] Globe.gl not loaded');
    return;
  }

  const themeDark = document.documentElement.dataset.theme !== 'light';

  globe = Globe()(el)
    .backgroundColor('rgba(0,0,0,0)')
    .globeImageUrl(themeDark
      ? 'https://unpkg.com/three-globe@2.31.0/example/img/earth-night.jpg'
      : 'https://unpkg.com/three-globe@2.31.0/example/img/earth-blue-marble.jpg'
    )
    .bumpImageUrl('https://unpkg.com/three-globe@2.31.0/example/img/earth-topology.png')
    .atmosphereColor(themeDark ? '#4ea8ff' : '#6aaef0')
    .atmosphereAltitude(0.22)
    .showGraticules(false)
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
      ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>'
      : '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 4 20 12 6 20 6 4"/></svg>';
    toggleBtn.title = autoRotate ? 'Pause rotation' : 'Resume rotation';
  });

  // Pause rotation on user interaction
  const pauseOnInteract = () => {
    if (!autoRotate) return;
    globe.controls().autoRotate = false;
    setTimeout(() => { if (autoRotate) globe.controls().autoRotate = true; }, 6000);
  };
  el.addEventListener('pointerdown', pauseOnInteract);
  el.addEventListener('wheel', pauseOnInteract, { passive: true });

  // Theme reactivity
  const mo = new MutationObserver(() => {
    const isDark = document.documentElement.dataset.theme !== 'light';
    globe.globeImageUrl(isDark
      ? 'https://unpkg.com/three-globe@2.31.0/example/img/earth-night.jpg'
      : 'https://unpkg.com/three-globe@2.31.0/example/img/earth-blue-marble.jpg'
    ).atmosphereColor(isDark ? '#4ea8ff' : '#6aaef0');
  });
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

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
    .ringColor(d => t => d._kind === 'selected'
      ? `rgba(167, 139, 250, ${1 - t})`      // violet
      : `rgba(255, 90, 95, ${1 - t})`)        // red
    .ringMaxRadius(d => d._kind === 'selected' ? 6 : 4)
    .ringPropagationSpeed(d => d._kind === 'selected' ? 3 : 2)
    .ringRepeatPeriod(d => d._kind === 'selected' ? 1100 : 1600);
}

function htmlTooltip(d) {
  const color = INTENSITY_COLOR[d.intensity] ?? INTENSITY_COLOR.medium;
  const label = INTENSITY_LABEL[d.intensity] ?? '—';
  return `
    <div style="font-family: Inter, sans-serif; padding: 9px 11px; border-radius: 10px;
                background: rgba(15,20,35,.92); color: #fff; border: 1px solid ${color};
                box-shadow: 0 10px 30px rgba(0,0,0,.4); max-width: 240px;">
      <div style="font-weight:700; margin-bottom:3px; font-size: .88rem;">${escapeHtml(d.name)}</div>
      <div style="font-size:.75rem; color:#9aa4b8;">${escapeHtml((d.countries ?? []).join(', '))}</div>
      <div style="margin-top:5px; display:inline-block; padding:2px 7px; border-radius:999px;
                  background:${color}22; color:${color}; font-size:.68rem; font-weight:600;">
        ${label} intensity
      </div>
    </div>
  `;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}
