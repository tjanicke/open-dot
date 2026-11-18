'use strict';
const $ = id => document.getElementById(id);
const LIMIT = 25;
let params = new URLSearchParams({kind: 'design'}), offset = 0, labels = {};

const SOURCE = {
  confirmed: ['Confirmed', 'Two independent sources agree (pay items, inventory, plan wording)', 'good'],
  pay_items: ['Pay items', 'From what the contract paid for', 'good'],
  inventory: ['Inventory', 'From the 2025 inventory; no type wording found on these sheets', 'info'],
  plan_text: ['Plan wording', 'From wording on the sheets; no usable inventory code', 'info'],
  ai: ['Local model', 'Read from the sheets by the local model', 'ai'],
  conflict: ['Check', 'Inventory and plan wording disagree', 'warn'],
  unknown: ['Unknown', 'No type evidence found', 'muted'],
};
const KIND = {design: 'New design', widening: 'Widening', rehab: 'Rehab / repair', maintenance: 'Maintenance', partial: 'Partial set', reference: 'Mentions only'};
const STATE = {proposed: 'proposed', existing: 'existing', replacement: 'replaces existing', unclear: '', 'superstructure replacement': 'superstructure replacement', 'deck replacement': 'deck replacement'};

function el(tag, text, cls, attrs) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  return e;
}
const fmtSN = sn => sn ? sn.slice(0, 3) + '-' + sn.slice(3) : '';
const ft = x => x ? Math.round(x).toLocaleString() + ' ft' : null;
const typeLabel = t => labels[t] || (t ? t.replaceAll('_', ' ') : 'Type unknown');
const pdfLink = (url, text) => url ? el('a', text, 'pdf', {href: url, target: '_blank', rel: 'noopener'})
  : el('span', text + ' · no verified IDOT link', 'nolink', {title: 'This PDF is not in the verified IDOT link catalogue yet'});

// Umami events: what visitors do, never what they typed.
function track(name, data) {
  try { if (window.umami && typeof window.umami.track === 'function') window.umami.track(name, data); } catch (_) {}
}
document.addEventListener('click', e => {
  const a = e.target.closest && e.target.closest('a');
  if (!a) return;
  if (a.id === 'export') track('Export CSV');
  else if (a.classList.contains('pdf')) track('Open plan PDF');
  else if (a.classList.contains('ext')) track('Open IDOT folder');
}, true);

async function api(url) {
  const r = await fetch(url);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Error(d.error || `Request failed (${r.status})`);
  return d;
}

async function loadStats() {
  const p = new URLSearchParams(params); p.delete('type');
  const d = await api('api/stats?' + p);
  const sel = $('type'), cur = params.get('type') || '';
  sel.replaceChildren(el('option', 'All types', null, {value: ''}));
  for (const t of d.types) {
    labels[t.id] = t.label;
    sel.append(el('option', `${t.label}  (${t.n.toLocaleString()})`, null, {value: t.id}));
  }
  sel.value = cur;
  $('meta').textContent = d.built ? `Index built ${d.built.slice(0, 10)}` + (d.reviews ? ` · ${d.reviews.toLocaleString()} model reviews` : '') : '';
}

function structureLine(s) {
  if (!s || !s.in_inventory) return 'Not in the 2025 inventory (may be replaced or renumbered)';
  const where = [s.carried, s.crossed && 'over ' + s.crossed].filter(Boolean).join(' ');
  const spans = (s.main_spans || 0) + (s.approach_spans || 0);
  return [where, s.county && s.county[0] + s.county.slice(1).toLowerCase() + ' Co.',
          s.built && 'built ' + s.built + (s.recon ? ` (rebuilt ${s.recon})` : ''),
          spans && `${spans} span${spans > 1 ? 's' : ''}`, ft(s.max_span) && 'max ' + ft(s.max_span),
          ft(s.length) && ft(s.length) + ' long'].filter(Boolean).join(' · ');
}

function typeBadge(g) {
  const [name, tip, cls] = SOURCE[g.type_source] || SOURCE.unknown;
  const wrap = el('span', null, 'typewrap');
  wrap.append(el('span', typeLabel(g.type), 'type'));
  if (g.variants && g.variants.length) wrap.append(el('span', g.variants.join(', '), 'variant'));
  wrap.append(el('span', name, 'src ' + cls, {title: tip}));
  return wrap;
}

function groupRow(g) {
  const row = el('div', null, 'set');
  const head = el('div', null, 'sethead');
  const when = el('div', null, 'when');
  when.append(el('strong', g.letting || 'date unknown'), el('span', 'Contract ' + (g.contract || '?'), 'muted'));
  const what = el('div', null, 'what');
  what.append(typeBadge(g));
  const desc = [KIND[g.kind] || g.kind, STATE[g.state], `${g.n_structural} structural sheet${g.n_structural === 1 ? '' : 's'}`].filter(Boolean).join(' · ');
  what.append(el('div', desc, 'muted small'));
  if (g.type_source === 'conflict') {
    const plan = Object.keys(g.plan_types || {})[0];
    what.append(el('div', `Plans mention ${typeLabel(plan)}; 2025 inventory says ${typeLabel(g.inv_type)}` + (g.era_match ? ' (built from this letting)' : ''), 'note warn'));
  }
  if (g.pay_evidence && g.pay_evidence.length) {
    // Maintenance / rehab rows: only that kind of work (a contract's other structures may be new builds).
    const upkeep = /WASH|CLEAN|PAINT|REPAIR|OVERLAY|SCARIF|BEARING|JOINT|SEAL|EPOXY|HYDRO|DECK/;
    let items = g.pay_evidence.filter(e => !/STRIP SEAL|PROTECTIVE/.test(e));
    if (g.kind === 'maintenance' || g.kind === 'rehab') items = items.filter(e => upkeep.test(e));
    const counts = new Map();
    for (const e of items) {            // "BRIDGE WASHING NO. 1", "… NO. 2" → "bridge washing ×2"
      const k = e.replace(/\s+NO\.?\s*\d+\s*$/, '').toLowerCase();
      counts.set(k, (counts.get(k) || 0) + 1);
    }
    const keep = [...counts].slice(0, 4).map(([k, n]) => n > 1 ? `${k} ×${n}` : k);
    if (keep.length) what.append(el('div', 'Paid for: ' + keep.join(' · '), 'note paid'));
  }
  if (g.ai_type && g.ai_quote) what.append(el('div', `“${g.ai_quote}”` + (g.ai_quote_ok ? '' : ' (not found verbatim)'), 'note quote'));
  const actions = el('div', null, 'actions');
  if (g.best_chunk) {
    const label = g.best_kind === 'general_plan' ? 'General plan' : 'Best sheet';
    actions.append(pdfLink(g.best_url, `${label} · p.${g.best_page}`));
  }
  if (g.eplan_link) actions.append(el('a', 'IDOT ↗', 'ext small', {href: g.eplan_link, target: '_blank', rel: 'noopener', title: 'Contract folder on IDOT eplan'}));
  const more = el('button', 'All sheets', 'ghost small', {type: 'button'});
  actions.append(more);
  head.append(when, what, actions);
  row.append(head);
  const list = el('div', null, 'sheets');
  list.hidden = true;
  more.addEventListener('click', async () => {
    if (!list.hidden) { list.hidden = true; more.textContent = 'All sheets'; return; }
    track('Show all sheets');
    if (!list.childElementCount) {
      const d = await api('api/group?id=' + g.id);
      for (const p of d.pages) {
        const r = el('div', null, 'sheet');
        r.append(pdfLink(p.url, 'p.' + p.page), el('span', p.kind_label || '', 'kind'),
                 el('span', p.title, 'title'), el('span', p.file, 'file muted', {title: p.file}));
        list.append(r);
      }
    }
    list.hidden = false; more.textContent = 'Hide sheets';
  });
  row.append(list);
  return row;
}

function card(item) {
  const c = el('article', null, 'card');
  const h = el('div', null, 'cardhead');
  if (item.sn) {
    h.append(el('h3', fmtSN(item.sn)), el('div', structureLine(item.structure), 'where'));
  } else {
    const g = item.groups[0] || {};
    h.append(el('h3', 'No structure number'), el('div', g.file || '', 'where'));
  }
  c.append(h);
  for (const g of item.groups) c.append(groupRow(g));
  if (item.other_groups > 0) {
    const b = el('button', `+ ${item.other_groups} other plan set${item.other_groups > 1 ? 's' : ''} for this structure`, 'ghost small', {type: 'button'});
    b.addEventListener('click', () => {
      const f = $('filters');
      f.reset(); f.q.value = fmtSN(item.sn); f.kind.value = 'any';
      f.requestSubmit();
    });
    c.append(b);
  }
  return c;
}

async function load() {
  const p = new URLSearchParams(params); p.set('offset', offset); p.set('limit', LIMIT);
  $('results').replaceChildren(el('div', 'Searching…', 'empty'));
  try {
    const d = await api('api/search?' + p);
    $('count').textContent = `${d.total.toLocaleString()} ${d.total === 1 ? 'structure' : 'structures'}`;
    $('results').replaceChildren(...d.items.map(card));
    if (!d.items.length) $('results').append(el('div', 'Nothing matches. Try “Anything” under Drawings, or clear a filter.', 'empty'));
    $('pager').hidden = d.total <= LIMIT;
    $('prev').disabled = offset === 0;
    $('next').disabled = offset + LIMIT >= d.total;
    $('pos').textContent = `${offset + 1}–${Math.min(offset + LIMIT, d.total)} of ${d.total.toLocaleString()}`;
    $('export').href = 'export.csv?' + params;
  } catch (e) {
    $('results').replaceChildren(el('div', e.message, 'empty error'));
  }
}

$('filters').addEventListener('submit', e => {
  e.preventDefault();
  params = new URLSearchParams();
  for (const [k, v] of new FormData(e.target)) if (String(v).trim()) params.set(k, String(v).trim());
  offset = 0;
  history.replaceState(null, '', '?' + params);
  track('Search', {filters: [...params.keys()].filter(k => k !== 'q').join(',') || 'none'});
  loadStats().catch(() => {});
  load();
});
$('prev').addEventListener('click', () => { offset = Math.max(0, offset - LIMIT); load(); scrollTo(0, 0); });
$('next').addEventListener('click', () => { offset += LIMIT; load(); scrollTo(0, 0); });

(async () => {
  const q = new URLSearchParams(location.search);
  if ([...q].length) params = q;
  const f = $('filters');
  await loadStats().catch(e => $('meta').textContent = e.message);
  for (const [k, v] of params) if (f.elements[k]) f.elements[k].value = v;
  load();
})();

// ---- Light / dark mode: follows the system setting until the visitor picks one, then remembers it ----
(() => {
  const KEY = 'opendot-bridgeplans-theme', root = document.documentElement, btn = $('theme');
  const media = window.matchMedia ? matchMedia('(prefers-color-scheme: dark)') : null;
  const saved = () => { try { const t = localStorage.getItem(KEY); return t === 'light' || t === 'dark' ? t : null; } catch (e) { return null; } };
  const apply = t => {
    root.setAttribute('data-theme', t);
    btn.textContent = t === 'dark' ? 'Light mode' : 'Dark mode';
    btn.setAttribute('aria-pressed', String(t === 'dark'));
  };
  apply(saved() || (media && media.matches ? 'dark' : 'light'));
  btn.addEventListener('click', () => {
    const t = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    apply(t);
    try { localStorage.setItem(KEY, t); } catch (e) {}
  });
  if (media && media.addEventListener) media.addEventListener('change', e => { if (!saved()) apply(e.matches ? 'dark' : 'light'); });
})();
