/* =========================================================
   Conflicts List — side-panel list synced with the globe.
   Click row → updates store.selectedId → globe zooms in.
   ========================================================= */

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const LOCALE = 'en-US';

const INTENSITY_COLOR = {
  low: '#4ea8ff',
  medium: '#ffb347',
  high: '#ff5a5f',
};
const INTENSITY_LABEL = { low: 'Low', medium: 'Medium', high: 'High' };
const INTENSITY_ORDER = { high: 0, medium: 1, low: 2 };

let state = {
  all: [],
  filter: 'all',
  query: '',
};
let refs = {};
let store = null;

export function initConflictsList(opts) {
  refs = {
    list:   $(opts.listEl),
    count:  $(opts.countEl),
    empty:  $(opts.emptyEl),
    search: $(opts.searchEl),
    filters: $$(opts.filterBtns),
  };
  state.all = (opts.conflicts ?? []).slice();
  store = opts.store;

  // Filter buttons
  refs.filters.forEach(btn => {
    btn.addEventListener('click', () => {
      refs.filters.forEach(b => {
        b.classList.remove('mini-chip--active');
        b.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('mini-chip--active');
      btn.setAttribute('aria-selected', 'true');
      state.filter = btn.dataset.intensity ?? 'all';
      render();
    });
  });

  // Search (debounced)
  let t;
  refs.search?.addEventListener('input', (e) => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.query = e.target.value.trim().toLowerCase();
      render();
    }, 140);
  });

  // React to selection changes from globe
  store?.subscribe((key, val) => {
    if (key !== 'selectedId') return;
    highlightSelected(val);
  });

  render();
}

function getFiltered() {
  let list = state.all;
  if (state.filter !== 'all') {
    list = list.filter(c => c.intensity === state.filter);
  }
  if (state.query) {
    const q = state.query;
    list = list.filter(c =>
      (c.name ?? '').toLowerCase().includes(q) ||
      (c.countries ?? []).some(x => x.toLowerCase().includes(q)) ||
      (c.tags ?? []).some(x => String(x).toLowerCase().includes(q))
    );
  }
  return list.slice().sort((a, b) => {
    const ia = INTENSITY_ORDER[a.intensity] ?? 99;
    const ib = INTENSITY_ORDER[b.intensity] ?? 99;
    if (ia !== ib) return ia - ib;
    return (a.name ?? '').localeCompare(b.name ?? '');
  });
}

function render() {
  const filtered = getFiltered();
  refs.count.textContent = filtered.length.toString();

  if (filtered.length === 0) {
    refs.list.innerHTML = '';
    refs.empty.hidden = false;
    return;
  }
  refs.empty.hidden = true;

  const selectedId = store?.get('selectedId');
  refs.list.innerHTML = filtered.map(c => buildRow(c, c.id === selectedId)).join('');

  $$('.conflict-row', refs.list).forEach(row => {
    row.addEventListener('click', () => {
      const id = row.dataset.id;
      const current = store?.get('selectedId');
      // Toggle: clicking selected row again collapses it
      store?.set('selectedId', current === id ? null : id);
    });
  });
}

function buildRow(c, selected) {
  const color = INTENSITY_COLOR[c.intensity] ?? INTENSITY_COLOR.medium;
  const label = INTENSITY_LABEL[c.intensity] ?? '—';
  const countries = (c.countries ?? []).join(', ');
  const year = c.startYear ? `· since ${c.startYear}` : '';

  const details = selected ? detailsHtml(c) : '';

  return `
    <li class="conflict-row" data-id="${escapeAttr(c.id)}" data-selected="${selected}" role="option" aria-selected="${selected}">
      <button type="button" class="conflict-row__btn" aria-expanded="${selected}">
        <span class="conflict-row__dot" style="background:${color}; color:${color};"></span>
        <span class="conflict-row__main">
          <span class="conflict-row__name">${escapeHtml(c.name ?? '—')}</span>
          <span class="conflict-row__meta">${escapeHtml(countries)} ${year}</span>
        </span>
        <span class="conflict-row__intensity intensity--${escapeAttr(c.intensity ?? 'low')}">${escapeHtml(label)}</span>
      </button>
      ${details}
    </li>
  `;
}

function detailsHtml(c) {
  return `
    <div class="conflict-row__details">
      <p>${escapeHtml(c.description ?? '')}</p>
      <dl>
        ${c.casualties ? `<dt>Casualties (est.)</dt><dd>${Number(c.casualties).toLocaleString(LOCALE)}</dd>` : ''}
        ${c.displaced ? `<dt>Displaced (est.)</dt><dd>${Number(c.displaced).toLocaleString(LOCALE)}</dd>` : ''}
        ${c.lastUpdate ? `<dt>Last update</dt><dd>${escapeHtml(c.lastUpdate)}</dd>` : ''}
      </dl>
    </div>
  `;
}

function highlightSelected(selectedId) {
  $$('.conflict-row', refs.list).forEach(row => {
    const isSel = row.dataset.id === selectedId;
    const wasSel = row.dataset.selected === 'true';
    if (isSel === wasSel) return;
    row.dataset.selected = String(isSel);
    row.setAttribute('aria-selected', String(isSel));
    row.querySelector('.conflict-row__btn')?.setAttribute('aria-expanded', String(isSel));

    const existing = row.querySelector('.conflict-row__details');
    if (isSel && !existing) {
      const conflict = state.all.find(c => c.id === selectedId);
      if (conflict) {
        row.insertAdjacentHTML('beforeend', detailsHtml(conflict));
      }
    } else if (!isSel && existing) {
      existing.remove();
    }
  });

  if (selectedId) {
    const sel = refs.list.querySelector(`[data-id="${cssEscape(selectedId)}"]`);
    if (sel) sel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

/* ---------- utils ---------- */
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}
function escapeAttr(s) { return escapeHtml(s).replace(/\s+/g, ' '); }
function cssEscape(s) {
  return (window.CSS && window.CSS.escape) ? window.CSS.escape(s) : String(s).replace(/"/g, '\\"');
}
