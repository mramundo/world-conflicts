/* =========================================================
   News — record/row layout (thumb | content | source/date).
   Filterable, searchable, progressively loaded.
   ========================================================= */

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const LOCALE = 'en-US';
const REL_LOCALE = 'en';
const PAGE_SIZE = 14;

let state = {
  items: [],
  filter: 'all',
  query: '',
  page: 1,
};

let refs = {};

export function initNews({ listEl, emptyEl, filterBtns, searchEl, loadMoreEl, items }) {
  refs = {
    list: $(listEl),
    empty: $(emptyEl),
    loadMore: $(loadMoreEl),
    search: $(searchEl),
    filters: $$(filterBtns),
  };
  state.items = Array.isArray(items) ? items : [];

  paintSkeletons(refs.list, 5);
  requestAnimationFrame(render);

  refs.filters.forEach(btn => {
    btn.addEventListener('click', () => {
      refs.filters.forEach(b => {
        b.classList.remove('chip--active');
        b.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('chip--active');
      btn.setAttribute('aria-selected', 'true');
      state.filter = btn.dataset.filter ?? 'all';
      state.page = 1;
      render();
    });
  });

  let t;
  refs.search?.addEventListener('input', (e) => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.query = e.target.value.trim().toLowerCase();
      state.page = 1;
      render();
    }, 180);
  });

  refs.loadMore?.addEventListener('click', () => {
    // Defensive: if everything is already on screen, don't bump state.page.
    // Keeps Load More idempotent on stray double-clicks and on clicks that
    // race filter/search updates.
    if (refs.loadMore.hidden) return;
    if (state.page * PAGE_SIZE >= getFiltered().length) {
      refs.loadMore.hidden = true;
      return;
    }
    state.page += 1;
    render({ append: true });
  });
}

function getFiltered() {
  let list = state.items;
  if (state.filter !== 'all') {
    list = list.filter(n => (n.categories ?? []).includes(state.filter));
  }
  if (state.query) {
    const q = state.query;
    list = list.filter(n =>
      (n.title ?? '').toLowerCase().includes(q) ||
      (n.description ?? '').toLowerCase().includes(q) ||
      (n.source ?? '').toLowerCase().includes(q) ||
      (n.tags ?? []).some(t => String(t).toLowerCase().includes(q))
    );
  }
  return list.slice().sort((a, b) =>
    new Date(b.publishedAt ?? 0) - new Date(a.publishedAt ?? 0)
  );
}

function render({ append = false } = {}) {
  const filtered = getFiltered();
  const end = state.page * PAGE_SIZE;
  const slice = filtered.slice(0, end);

  if (!append) refs.list.innerHTML = '';

  if (slice.length === 0) {
    refs.list.innerHTML = '';
    refs.empty.hidden = false;
    refs.loadMore.hidden = true;
    return;
  }
  refs.empty.hidden = true;

  const startIdx = append ? (state.page - 1) * PAGE_SIZE : 0;
  const toRender = append ? slice.slice(startIdx) : slice;

  toRender.forEach((item, i) => {
    refs.list.appendChild(buildRow(item, i));
  });

  refs.loadMore.hidden = slice.length >= filtered.length;
}

function buildRow(n, i) {
  const li = document.createElement('li');
  li.className = 'news-row';
  li.style.animationDelay = `${Math.min(i, 10) * 30}ms`;

  const initial = (n.source ?? '?').charAt(0).toUpperCase();
  const thumb = n.image
    ? `<img loading="lazy" alt="" src="${escapeAttr(n.image)}" onerror="this.remove();this.parentElement.querySelector('.news-row__thumb-fallback').style.display='flex';"/>
       <span class="news-row__thumb-fallback" style="display:none">${escapeHtml(initial)}</span>`
    : `<span class="news-row__thumb-fallback">${escapeHtml(initial)}</span>`;

  const firstTags = (n.categories ?? []).slice(0, 2);

  li.innerHTML = `
    <a href="${escapeAttr(n.url ?? '#')}" target="_blank" rel="noopener noreferrer" aria-label="${escapeAttr(n.title ?? '')}">
      <div class="news-row__thumb">${thumb}</div>
      <div class="news-row__body">
        <h3 class="news-row__title">${escapeHtml(n.title ?? '')}</h3>
        ${n.description ? `<p class="news-row__desc">${escapeHtml(n.description)}</p>` : ''}
        ${firstTags.length ? `<div class="news-row__tags">${firstTags.map(t => `<span class="news-row__tag" data-k="${escapeAttr(t)}">${escapeHtml(categoryLabel(t))}</span>`).join('')}</div>` : ''}
      </div>
      <div class="news-row__meta">
        <span class="news-row__source">${escapeHtml(n.source ?? 'Source')}</span>
        <time class="news-row__date" datetime="${escapeAttr(n.publishedAt ?? '')}">${formatRelative(n.publishedAt)}</time>
        <svg class="news-row__arrow" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
      </div>
    </a>
  `;
  return li;
}

function paintSkeletons(container, n) {
  if (!container) return;
  container.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const sk = document.createElement('li');
    sk.className = 'news-row news-row--skeleton';
    sk.innerHTML = `
      <div class="news-row__thumb"></div>
      <div class="news-row__body">
        <div class="sk sk--lg sk--w80"></div>
        <div class="sk sk--w60"></div>
        <div class="sk sk--w40"></div>
      </div>
      <div class="news-row__meta">
        <div class="sk sk--w40" style="width:60px"></div>
        <div class="sk sk--w40" style="width:40px"></div>
      </div>
    `;
    container.appendChild(sk);
  }
}

const CATEGORY_LABELS = {
  conflict: 'Conflict',
  analysis: 'Analysis',
  humanitarian: 'Humanitarian',
};
function categoryLabel(key) { return CATEGORY_LABELS[key] ?? key; }

function formatRelative(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  const diffMs = Date.now() - d.getTime();
  const diffMin = Math.round(diffMs / 60000);
  const rtf = new Intl.RelativeTimeFormat(REL_LOCALE, { numeric: 'auto' });
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return rtf.format(-diffMin, 'minute');
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return rtf.format(-diffH, 'hour');
  const diffD = Math.round(diffH / 24);
  if (diffD < 7) return rtf.format(-diffD, 'day');
  return new Intl.DateTimeFormat(LOCALE, { day: '2-digit', month: 'short', year: 'numeric' }).format(d);
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}
function escapeAttr(s) { return escapeHtml(s).replace(/\s+/g, ' '); }
