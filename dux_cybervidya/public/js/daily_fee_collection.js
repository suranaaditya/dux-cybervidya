/* ============================================================================
   dux_cybervidya — Daily Fee Collection dashboard (Frappe Page build)

   Ported from the approved finance_dashboard mockup. The visual design and
   interaction model are unchanged; the only substitution is the data source:
   the seeded in-memory dataset is replaced by six whitelisted controllers in
   dux_cybervidya.api.dashboard. The rejection / failed-post panel is removed.

   Exposes a single entry point: window.DuxCyberVidyaDashboard.init(rootEl).
   Every DOM lookup is scoped to rootEl so multiple desk pages never collide.
   ========================================================================== */
window.DuxCyberVidyaDashboard = (function () {
'use strict';

/* ---------- Indian number formatting (lifted from the mockup's data.js) ---- */
function fmtINR(n) {
  n = Math.round(n);
  var neg = n < 0; n = Math.abs(n);
  var s = String(n), last3 = s.slice(-3), rest = s.slice(0, -3);
  if (rest) last3 = ',' + last3;
  rest = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  return (neg ? '-' : '') + rest + last3;
}
var rupee = function (n) { return '₹ ' + fmtINR(n); };          // ₹ + thin space
function fmtShort(n) {
  var neg = n < 0, a = Math.abs(n), out;
  if (a >= 1e7) out = (a / 1e7).toFixed(2).replace(/\.?0+$/, '') + ' Cr';
  else if (a >= 1e5) out = (a / 1e5).toFixed(2).replace(/\.?0+$/, '') + ' L';
  else out = fmtINR(a);
  return (neg ? '-' : '') + out;
}

/* ---------- trust-group + institution master (mirrors server constants) ---- */
var TRUST_GROUPS = [
  ['ASS',  'Ankush Shikshan Sanstha (ASS)',                       ['GHRCE', 'GHRIETN', 'GHRILS', 'GHRLS']],
  ['EMF',  'GH Raisoni Educational & Medical Foundation (GHREMF)', ['GHRCEM', 'GHRCACS', 'GHRPSP']],
  ['EF',   'GH Raisoni Education Foundation Jalgaon (GHREF)',      ['GHRJCJ', 'GHRIBM', 'GHRPSJ', 'SRWC']],
  ['RF',   'GH Raisoni Foundation (GHRF)',                         ['GHRSBM', 'GHRPSA']],
  ['CBS',  'Chaitanya Bahuudeshiya Sanstha (CBS)',                 ['GHRIMR']],
  ['UA',   'GH Raisoni University Amravati (GHRUA)',               ['GHRUA']],
  ['STUN', 'GH Raisoni Skill Tech University Nagpur',              ['GHRSTU']],
  ['STUP', 'GH Raisoni International Skill Tech University Pune',   ['GHRISTU']],
  ['US',   'GH Raisoni University Saikheda (GHRUS)',               ['GHRUS']],
];
var GROUPS = TRUST_GROUPS.map(function (g) { return { key: g[0], name: g[1], n: g[2].length }; });
var INST = [];
TRUST_GROUPS.forEach(function (g) { g[2].forEach(function (c) { INST.push({ code: c, group: g[0], groupName: g[1] }); }); });
var groupOf = {}; INST.forEach(function (i) { groupOf[i.code] = i.group; });
var WK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
var MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/* ---------- root-scoped DOM helpers ---------- */
var ROOT = null;
var $ = function (s) { return ROOT.querySelector(s); };
var $$ = function (s) { return Array.prototype.slice.call(ROOT.querySelectorAll(s)); };
var el = function (t, c) { var e = document.createElement(t); if (c) e.className = c; return e; };
var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>]/g, function (m) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[m]; }); };
function pad(n) { return String(n).padStart(2, '0'); }

/* ---------- state ---------- */
var state = {
  direction: 'both', dateKey: 'yesterday', cs: null, ce: null,
  groups: [], insts: [], channel: 'all', status: 'active', source: 'all',
  sortCol: 'net', sortDir: 'desc', expandedCode: null,
  search: '', recent: [],
};
var lastInst = [];   // cache of the last inst_table response for client-side re-sort

/* ---------- date helpers ---------- */
function localISO(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
function isoDaysAgo(n) { var d = new Date(); d.setDate(d.getDate() - n); return localISO(d); }
function fyStartISO() {
  var d = new Date(), y = d.getFullYear();
  if (d.getMonth() + 1 < 4) y -= 1;   // FY (India) starts 1 Apr
  return y + '-04-01';
}
function dateRangeFilters() {
  switch (state.dateKey) {
    case 'yesterday': return { date_from: null, date_to: null };   // server fills (IST yesterday)
    case 'week':      return { date_from: isoDaysAgo(7),  date_to: isoDaysAgo(1) };
    case 'month':     return { date_from: isoDaysAgo(30), date_to: isoDaysAgo(1) };
    case 'fyytd':     return { date_from: fyStartISO(),   date_to: isoDaysAgo(1) };
    case 'custom':    return { date_from: state.cs, date_to: state.ce };
  }
  return { date_from: null, date_to: null };
}
function rangeLabel() {
  var r = dateRangeFilters();
  var f = r.date_from || isoDaysAgo(1), t = r.date_to || isoDaysAgo(1);
  if (f === t) return prettyDate(f);
  return prettyDate(f) + ' – ' + prettyDate(t);
}
function prettyDate(iso) { if (!iso) return ''; var p = iso.split('-'); return (+p[2]) + ' ' + MO[+p[1] - 1] + ' ' + p[0]; }
function prettyDateTime(iso) {
  if (!iso) return '';
  var d = new Date(iso);
  return WK[d.getDay()] + ' ' + d.getDate() + ' ' + MO[d.getMonth()] + ' · ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

/* ---------- server call ---------- */
function call(method, filters, extra) {
  var args = { filters: JSON.stringify(filters) };
  if (extra) Object.keys(extra).forEach(function (k) { args[k] = extra[k]; });
  return frappe.call({ method: 'dux_cybervidya.api.dashboard.' + method, args: args }).then(function (r) { return r.message; });
}
function currentFilters() {
  var r = dateRangeFilters();
  return {
    direction: state.direction, date_from: r.date_from, date_to: r.date_to,
    trust_groups: state.groups, institutions: state.insts,
    channel: state.channel, status: state.status, source: state.source,
  };
}
function isDefault() {
  return state.direction === 'both' && state.dateKey === 'yesterday' && !state.groups.length &&
    !state.insts.length && state.channel === 'all' && state.status === 'active' && state.source === 'all';
}

/* ======================================================================
   RENDER ORCHESTRATION
   ====================================================================== */
function renderAll() {
  flashLoading();
  var f = currentFilters();
  return Promise.all([
    call('summary', f), call('daily', f), call('inst_table', f),
    call('throughflow', f), call('feed', f),
  ]).then(function (res) {
    var sum = res[0], daily = res[1], inst = res[2], flow = res[3], feed = res[4];
    lastInst = inst || [];
    renderStatPills(sum);
    renderSummary(sum);
    renderChart(daily);
    renderInstTable();
    renderThroughflow(flow);
    renderFeed(feed);
    syncControls();
    $('.clearall').classList.toggle('show', !isDefault());
  }).catch(function (e) { console.error('[dux dashboard] render failed', e); });
}
function flashLoading() {
  $$('.cvfade').forEach(function (n) { n.classList.add('loading'); });
  clearTimeout(flashLoading._t);
  flashLoading._t = setTimeout(function () { $$('.cvfade').forEach(function (n) { n.classList.remove('loading'); }); }, 320);
}

/* ---- status pills (A) — amber cancelled pill only ---- */
function renderStatPills(sum) {
  var box = $('#statpills'); box.innerHTML = '';
  var n = (sum && sum.cancelled && sum.cancelled.count) || 0;
  if (n > 0) {
    var p = el('div', 'statpill amber');
    p.innerHTML = '<span class="dot"></span>' + n + ' cancelled in scope';
    p.onclick = function () { setStatus('cancelled'); };
    box.appendChild(p);
  }
}

/* ---- summary band (C) ---- */
function renderSummary(s) {
  s = s || { collections: {}, refunds: {}, cancelled: {} };
  var cT = s.collections.total || 0, cN = s.collections.count || 0;
  var rT = s.refunds.total || 0, rN = s.refunds.count || 0;
  var net = (typeof s.net === 'number') ? s.net : (cT - rT);
  var cancT = s.cancelled.total || 0, cancN = s.cancelled.count || 0;
  var primaryCancel = state.status === 'cancelled';

  var html = '';
  html += sumCard('c', 'Collections', cT, cN + ' JEs', 'collections', false);
  html += sumCard('r', 'Refunds', rT, rN + ' JEs', 'refunds', false);
  html += sumCard('n', 'Net', net, 'collections − refunds', null, false);
  if (cancN > 0) html += sumCard('x', 'Cancelled (in scope)', cancT, cancN + ' JEs', 'cancelled', primaryCancel);
  $('#summary').innerHTML = html;
  $$('#summary .sumcard').forEach(function (n) {
    n.onclick = function () {
      var a = n.dataset.act;
      if (a === 'collections') setDirection('collections');
      else if (a === 'refunds') setDirection('refunds');
      else if (a === 'cancelled') setStatus('cancelled');
    };
  });
}
function sumCard(cls, k, v, m, act, primary) {
  return '<div class="sumcard ' + cls + (primary ? ' primary tint-' + cls : '') + '"' + (act ? ' data-act="' + act + '"' : '') + '>' +
    '<div class="k">' + k + '</div><div class="v">' + rupee(v) + '</div><div class="m">' + m + '</div></div>';
}

/* ---- daily activity chart (D) ---- */
var chart = null;
function renderChart(daily) {
  daily = daily || [];
  var labels = [], coll = [], ref = [], net = [], counts = [];
  daily.forEach(function (d) {
    var p = d.date.split('-');
    labels.push((+p[2]) + ' ' + MO[+p[1] - 1]);
    coll.push(d.collections); ref.push(-d.refunds); net.push(d.net); counts.push(d.count);
  });
  var cv = $('#dailyChart'); if (!cv) return;
  if (chart) chart.destroy();
  chart = new Chart(cv.getContext('2d'), {
    data: {
      labels: labels,
      datasets: [
        { type: 'bar', label: 'Collections', data: coll, backgroundColor: '#059669', stack: 's', borderRadius: 2, order: 3 },
        { type: 'bar', label: 'Refunds', data: ref, backgroundColor: '#d97706', stack: 's', borderRadius: 2, order: 3 },
        { type: 'line', label: 'Net', data: net, borderColor: '#2563eb', backgroundColor: '#2563eb', borderWidth: 2, pointRadius: labels.length > 30 ? 0 : 2.5, tension: .25, order: 1 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      onClick: function (e, items) { if (items && items.length) { var d = daily[items[0].index]; if (d) setCustomDay(d.date); } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { family: "'Geist Mono'", size: 10 }, color: '#9ca3af', maxRotation: 0, autoSkip: true, maxTicksLimit: 16 } },
        y: { grid: { color: '#f0f2f5' }, ticks: { font: { family: "'Geist Mono'", size: 10 }, color: '#9ca3af', callback: function (v) { return fmtShort(v); } } },
      },
      plugins: {
        legend: { display: true, position: 'top', align: 'end', labels: { boxWidth: 10, boxHeight: 10, font: { family: "'Geist'", size: 11 }, color: '#6b7280', usePointStyle: true } },
        tooltip: {
          backgroundColor: '#111827', padding: 11, titleFont: { family: "'Geist'", size: 12 }, bodyFont: { family: "'Geist Mono'", size: 11.5 }, cornerRadius: 8, displayColors: true, boxPadding: 4,
          callbacks: {
            title: function (it) { return it[0].label; },
            label: function (it) { return it.dataset.label + '  ' + rupee(Math.abs(it.raw)); },
            afterBody: function (it) { return 'JEs  ' + counts[it[0].dataIndex]; },
          },
        },
      },
    },
  });
}

/* ---- institution table (E) ---- */
function sortedInst() {
  var rows = lastInst.slice();
  var dir = state.sortDir === 'asc' ? 1 : -1, col = state.sortCol;
  rows.sort(function (a, b) {
    if (col === 'c') return (a.collections - b.collections) * dir;
    if (col === 'r') return (a.refunds - b.refunds) * dir;
    if (col === 'n') return (a.count - b.count) * dir;
    if (col === 'last') return ((a.last_activity || '') < (b.last_activity || '') ? -1 : 1) * dir;
    return (a.net - b.net) * dir;   // net (default)
  });
  return rows;
}
function renderInstTable() {
  var rows = sortedInst();
  var tb = $('#instBody'); tb.innerHTML = '';
  if (!rows.length) { tb.innerHTML = emptyRow(8, 'No journal entries in scope', 'Broaden the date range or clear a filter to see activity.'); markSort(); return; }
  rows.forEach(function (a) {
    var tr = el('tr', 'drow'); tr.dataset.code = a.code;
    if (state.expandedCode === a.code) tr.classList.add('expanded');
    tr.innerHTML =
      '<td><span class="code">' + esc(a.code) + '</span></td>' +
      '<td>' + esc(a.company) + '</td>' +
      '<td class="muted" style="font-size:12px">' + esc(a.group_name) + '</td>' +
      '<td class="r g">' + amt(a.collections) + '</td>' +
      '<td class="r a">' + amt(a.refunds) + '</td>' +
      '<td class="r bold">' + amt(a.net) + '</td>' +
      '<td><span class="jepill">' + a.count + '</span></td>' +
      '<td class="muted" style="font-size:12px">' + relTime(a.last_activity) + '</td>';
    tr.onclick = function () { toggleExpand(a.code); };
    tb.appendChild(tr);
    if (state.expandedCode === a.code) tb.appendChild(expandRow(a));
  });
  markSort();
}
function expandRow(a) {
  var tr = el('tr', 'exprow'); var td = el('td', 'exp-cell'); td.colSpan = 8;
  td.innerHTML =
    '<div class="exp-inner">' +
      '<div><h5>' + esc(a.code) + ' · daily activity</h5><div class="exp-chart"><canvas id="expChart"></canvas></div>' +
        '<div class="exp-link"><a data-feed="' + esc(a.code) + '">View JE feed for this institution →</a></div></div>' +
      '<div><h5>Bank ledgers · ' + esc(a.abbr || a.code) + '</h5>' +
        '<table class="minitable"><thead><tr><th>Ledger</th><th class="r">Collections</th><th class="r">Refunds</th><th class="r">Net</th><th>JEs</th></tr></thead>' +
        '<tbody id="expLedgers"><tr><td colspan="5" class="muted" style="padding:10px">Loading…</td></tr></tbody></table></div>' +
    '</div>';
  tr.appendChild(td);
  // async: scoped daily (mini chart) + scoped feed (ledger breakdown)
  var f = currentFilters(); f.institutions = [a.code];
  call('daily', f).then(function (d) { drawInstMiniChart(d || []); });
  call('feed', f, { limit: 100 }).then(function (list) { fillExpandLedgers(list || []); });
  setTimeout(function () {
    var fl = td.querySelector('[data-feed]');
    if (fl) fl.onclick = function (e) { e.stopPropagation(); $('#refsearch').value = a.code; doSearch(a.code); $('#feedCard').scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  }, 0);
  return tr;
}
function fillExpandLedgers(list) {
  var body = $('#expLedgers'); if (!body) return;
  var led = {};
  list.forEach(function (j) {
    var x = led[j.ledger] || (led[j.ledger] = { ledger: j.ledger, c: 0, r: 0, n: 0 });
    if (j.direction === 'collection') x.c += j.amount; else x.r += j.amount; x.n++;
  });
  var keys = Object.keys(led);
  if (!keys.length) { body.innerHTML = '<tr><td colspan="5" class="muted" style="padding:10px">No ledgers in scope.</td></tr>'; return; }
  body.innerHTML = keys.map(function (k) {
    var x = led[k];
    return '<tr><td class="mono" style="font-size:11.5px">' + esc(x.ledger) + '</td><td class="r g">' + amt(x.c) + '</td><td class="r a">' + amt(x.r) + '</td><td class="r bold">' + amt(x.c - x.r) + '</td><td><span class="jepill">' + x.n + '</span></td></tr>';
  }).join('') + (list.length >= 100 ? '<tr><td colspan="5" class="dim" style="font-size:11px;padding:6px 10px">Based on the 100 most recent entries in scope.</td></tr>' : '');
}
var miniChart = null;
function drawInstMiniChart(daily) {
  var cv = $('#expChart'); if (!cv) return;
  var labels = [], coll = [], ref = [], net = [];
  daily.forEach(function (d) { var p = d.date.split('-'); labels.push((+p[2]) + '/' + (+p[1])); coll.push(d.collections); ref.push(-d.refunds); net.push(d.net); });
  if (miniChart) miniChart.destroy();
  miniChart = new Chart(cv.getContext('2d'), {
    data: { labels: labels, datasets: [
      { type: 'bar', data: coll, backgroundColor: '#059669', stack: 's', borderRadius: 2 },
      { type: 'bar', data: ref, backgroundColor: '#d97706', stack: 's', borderRadius: 2 },
      { type: 'line', data: net, borderColor: '#2563eb', borderWidth: 1.5, pointRadius: 0, tension: .25 },
    ] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { grid: { display: false }, ticks: { font: { size: 9, family: "'Geist Mono'" }, color: '#9ca3af', maxTicksLimit: 10, maxRotation: 0 } }, y: { grid: { color: '#f0f2f5' }, ticks: { font: { size: 9, family: "'Geist Mono'" }, color: '#9ca3af', callback: function (v) { return fmtShort(v); } } } } },
  });
}
function toggleExpand(code) { state.expandedCode = state.expandedCode === code ? null : code; renderInstTable(); }

/* ---- bank-ledger throughflow (F) ---- */
function renderThroughflow(rows) {
  rows = rows || [];
  var tb = $('#flowBody'); tb.innerHTML = '';
  if (!rows.length) { tb.innerHTML = emptyRow(6, 'No ledger activity', 'No bank or cash ledger has settled activity in the fixed windows.'); return; }
  rows.forEach(function (R) {
    var tr = el('tr', 'drow');
    tr.innerHTML =
      '<td><span class="code">' + esc(R.abbr || R.code) + '</span><div class="co2">' + esc(R.company) + '</div></td>' +
      '<td class="mono" style="font-size:11.5px">' + esc(R.ledger) + (R.is_pooled ? '<span class="poolbadge" data-tip="Used by ' + R.pooled_count + ' institutions; rows are per-institution to preserve attribution.">Pooled</span>' : '') + '</td>' +
      '<td class="r">' + amt(R.yesterday) + '</td>' +
      '<td class="r">' + amt(R.week) + '</td>' +
      '<td class="r">' + amt(R.month) + '</td>' +
      '<td class="sparkcell">' + sparkSVG(R.spark || []) + '</td>';
    tr.onclick = function () { openLedgerDrawer(R); };
    tb.appendChild(tr);
  });
  wireTooltips();
}
function sparkSVG(vals) {
  var w = 88, h = 26, max = Math.max.apply(null, vals.concat(1)), n = vals.length, bw = w / (n || 1);
  var bars = vals.map(function (v, i) {
    var bh = (Math.abs(v) / (max || 1)) * (h - 4);
    return '<rect x="' + (i * bw + 1).toFixed(1) + '" y="' + (h - bh - 1).toFixed(1) + '" width="' + (bw - 1.5).toFixed(1) + '" height="' + Math.max(bh, 1).toFixed(1) + '" rx="1" fill="' + (i === n - 1 ? '#2563eb' : '#cbd5e1') + '"/>';
  }).join('');
  return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">' + bars + '</svg>';
}

/* ---- activity feed (G) ---- */
function renderFeed(list) {
  list = list || [];
  var q = state.search.trim();
  $('#feedHead').textContent = q ? "Recent activity — matching ‘" + q + "’" : 'Recent activity';
  $('#feedSub').textContent = list.length + ' of last 50 entries in scope';
  var tl = $('#timeline'); tl.innerHTML = '';
  if (!list.length) { tl.innerHTML = '<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg><div class="t">Nothing matches</div><div class="s">Try a different reference or broaden the date range.</div></div>'; renderRecentChips(); return; }
  list.forEach(function (j) {
    var cls = j.status === 'Cancelled' ? 'x' : (j.direction === 'collection' ? 'c' : 'r');
    var it = el('div', 'tlitem');
    it.innerHTML =
      '<div class="tldot ' + cls + '"></div>' +
      '<div class="tlbody"><div class="tlrow1"><div class="tlmeta"><b>' + esc(j.abbr || j.code) + '</b><span class="ch">' + cap(j.channel) + (j.direction === 'refund' ? ' · refund' : '') + '</span></div>' +
      '<div class="tlamt' + (j.status === 'Cancelled' ? ' struck' : '') + '">' + (j.direction === 'refund' ? '−' : '') + rupee(j.amount) + '</div></div>' +
      '<div class="tlref">' + esc(j.ref) + '</div>' +
      '<div class="tltime">' + prettyDateTime(j.dt) + '</div>' +
      (j.status === 'Cancelled' && j.replaced_by_ref ? '<div class="tlcancel">Cancelled — see <a data-search="' + esc(j.replaced_by_ref) + '">' + esc(j.replaced_by_ref) + '</a></div>' : (j.status === 'Cancelled' ? '<div class="tlcancel">Cancelled</div>' : '')) +
      '</div>';
    it.onclick = function (e) { if (e.target.dataset.search) { e.stopPropagation(); doSearch(e.target.dataset.search); return; } openJEDrawer(j); };
    tl.appendChild(it);
  });
  renderRecentChips();
}
function renderRecentChips() {
  var rc = $('#recentChips');
  rc.innerHTML = '<span class="lab">Recent searches</span>' +
    state.recent.slice(0, 3).map(function (r) { return '<span class="chip" data-r="' + esc(r) + '">' + esc(r) + '</span>'; }).join('');
  $$('#recentChips .chip').forEach(function (c) { c.onclick = function () { $('#refsearch').value = c.dataset.r; doSearch(c.dataset.r); }; });
}
function doSearch(q) {
  q = (q || '').trim();
  var f = currentFilters();
  if (!q) { state.search = ''; call('feed', f).then(renderFeed); return; }
  state.search = q; addRecent(q);
  f.q = q;   // server-side reference filter (LIKE %q%)
  call('feed', f).then(function (list) {
    list = list || [];
    var exact = list.filter(function (j) { return j.ref === q; });
    if (exact.length) { openJEDrawer(exact[0]); }
    renderFeed(list);
  });
}
function addRecent(q) { if (!q) return; state.recent = [q].concat(state.recent.filter(function (x) { return x !== q; })).slice(0, 6); }

/* ======================================================================
   DRAWER
   ====================================================================== */
function openDrawer() { $('#scrim').classList.add('open'); $('#drawer').classList.add('open'); }
function closeDrawer() { $('#scrim').classList.remove('open'); $('#drawer').classList.remove('open'); }

function openLedgerDrawer(R) {
  var f = currentFilters(); f.ledger = R.ledger; f.institution = R.code;
  call('feed', f, { limit: 100 }).then(function (list) {
    list = list || [];
    $('#drawer').innerHTML = drawerHead('Bank ledger throughflow', R.ledger + ' · ' + (R.abbr || R.code) + ' · ' + rangeLabel()) +
      '<div class="drawer-body">' + (list.length ? list.map(jeEntry).join('') : emptyDrawer()) + '</div>';
    wireDrawer(); openDrawer();
  });
}
function openJEDrawer(j) {
  $('#drawer').innerHTML = drawerHead('Journal Entry', j.name) +
    '<div class="drawer-body">' +
      jeEntry(j) +
      '<div class="drawer-note"><b>' + esc(j.company) + '</b> · ' + esc((groupOf[j.code] ? (GROUPS.find(function (g) { return g.key === groupOf[j.code]; }) || {}).name : '') || '') + '<br>Ledger: <span class="mono">' + esc(j.ledger) + '</span><br>Source: ' + cap(j.source) +
        (j.status === 'Cancelled' && j.replaced_by_ref ? '<br><span style="color:var(--cancel)">Cancelled</span> — reposted as <span class="mono">' + esc(j.replaced_by_ref) + '</span>.' : (j.status === 'Cancelled' ? '<br><span style="color:var(--cancel)">Cancelled</span>.' : '')) +
      '</div>' +
    '</div>';
  wireDrawer(); openDrawer();
}
function drawerHead(t, s) {
  return '<div class="drawer-h"><div><div class="dt">' + esc(t) + '</div><div class="ds">' + esc(s) + '</div></div>' +
    '<div class="drawer-close" id="drawerClose"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="6" y1="18" x2="18" y2="6"/></svg></div></div>';
}
function jeEntry(j) {
  var cls = j.status === 'Cancelled' ? 'x' : (j.direction === 'collection' ? 'c' : 'r');
  var link = '/app/journal-entry/' + encodeURIComponent(j.name);
  return '<div class="jeentry"><div class="jedot tldot ' + cls + '" style="margin-top:6px"></div>' +
    '<div style="flex:1; min-width:0"><div class="jdate">' + prettyDateTime(j.dt) + '</div>' +
    '<div class="jref">' + esc(j.ref) + '</div>' +
    '<div class="jch">' + cap(j.channel) + ' · ' + (j.direction === 'refund' ? 'Refund' : 'Collection') + (j.status === 'Cancelled' ? ' · <span style="color:var(--cancel)">Cancelled</span>' : '') + '</div></div>' +
    '<div class="jamt"><div class="a' + (j.status === 'Cancelled' ? ' struck' : '') + '" style="' + (j.status === 'Cancelled' ? 'text-decoration:line-through;color:var(--tx3)' : '') + '">' + (j.direction === 'refund' ? '−' : '') + rupee(j.amount) + '</div>' +
    '<a href="' + link + '" target="_blank">Open in ERPNext →</a></div></div>';
}
function emptyDrawer() { return '<div class="empty"><div class="t">No entries</div><div class="s">No journal entries touched this ledger in the selected range.</div></div>'; }
function wireDrawer() { var c = $('#drawerClose'); if (c) c.onclick = closeDrawer; }

/* ======================================================================
   CONTROLS
   ====================================================================== */
function setDirection(v) { state.direction = v; renderAll(); }
function setStatus(v) { state.status = v; renderAll(); }
function setCustomDay(iso) { state.dateKey = 'custom'; state.cs = iso; state.ce = iso; renderAll(); $('#instCard').scrollIntoView({ behavior: 'smooth', block: 'start' }); }

function syncControls() {
  segSync('seg-direction', state.direction);
  segSync('seg-date', state.dateKey);
  segSync('seg-channel', state.channel);
  segSync('seg-status', state.status);
  segSync('seg-source', state.source);
  $('#customRange').classList.toggle('show', state.dateKey === 'custom');
  updMselLabel('group', state.groups);
  updMselLabel('inst', state.insts);
}
function segSync(id, val) { $$('#' + id + ' button').forEach(function (b) { b.classList.toggle('on', b.dataset.v === val); }); }
function updMselLabel(which, sel) {
  var btn = $('#msel-' + which + ' .label');
  if (!sel.length) { btn.textContent = 'All'; return; }
  if (sel.length <= 3) { btn.textContent = sel.join(', '); return; }
  btn.textContent = sel.slice(0, 2).join(', ') + ', +' + (sel.length - 2);
}

function wireSegments() {
  [['seg-direction', 'direction'], ['seg-date', 'dateKey'], ['seg-channel', 'channel'], ['seg-status', 'status'], ['seg-source', 'source']].forEach(function (p) {
    $$('#' + p[0] + ' button').forEach(function (b) { b.onclick = function () { state[p[1]] = b.dataset.v; renderAll(); }; });
  });
}
function wireCustom() {
  var s = $('#cstart'), e = $('#cend');
  s.value = state.cs || isoDaysAgo(1); e.value = state.ce || isoDaysAgo(1);
  function apply() {
    if (s.value) state.cs = s.value;
    if (e.value) state.ce = e.value;
    if (state.cs && state.ce && state.cs > state.ce) { var t = state.cs; state.cs = state.ce; state.ce = t; s.value = state.cs; e.value = state.ce; }
    state.dateKey = 'custom'; renderAll();
  }
  s.onchange = apply; e.onchange = apply;
}

/* multiselect builder */
function buildMsel(which, list, searchable) {
  var pop = $('#msel-' + which + ' .msel-pop');
  var listEl = $('#msel-' + which + ' .msel-list');
  function draw() {
    var sel = which === 'group' ? state.groups : state.insts;
    var filter = searchable ? ($('#msel-' + which + ' .search').value || '').toLowerCase() : '';
    listEl.innerHTML = list.filter(function (o) { return !filter || (o.name + ' ' + o.key).toLowerCase().indexOf(filter) >= 0; }).map(function (o) {
      var on = sel.indexOf(o.key) >= 0;
      var metaTxt = which === 'group' ? o.n + ' inst' : o.group;
      return '<div class="msel-opt' + (on ? ' sel' : '') + '" data-k="' + esc(o.key) + '"><div class="box"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div>' +
        '<span>' + esc(o.name) + '</span><span class="meta">' + esc(metaTxt || '') + '</span></div>';
    }).join('');
    $$('#msel-' + which + ' .msel-opt').forEach(function (opt) {
      opt.onclick = function () {
        var k = opt.dataset.k, arr = which === 'group' ? state.groups : state.insts;
        var i = arr.indexOf(k); if (i >= 0) arr.splice(i, 1); else arr.push(k);
        draw(); renderAll();
      };
    });
  }
  $('#msel-' + which + ' .msel-btn').onclick = function (e) { e.stopPropagation(); closeAllMsel(pop); pop.classList.toggle('open'); draw(); if (searchable) setTimeout(function () { var s = $('#msel-' + which + ' .search'); if (s) s.focus(); }, 0); };
  if (searchable) $('#msel-' + which + ' .search').oninput = draw;
  $('#msel-' + which + ' .selall').onclick = function () { var arr = list.map(function (o) { return o.key; }); if (which === 'group') state.groups = arr.slice(); else state.insts = arr.slice(); draw(); renderAll(); };
  $('#msel-' + which + ' .clr').onclick = function () { if (which === 'group') state.groups = []; else state.insts = []; draw(); renderAll(); };
  pop.onclick = function (e) { e.stopPropagation(); };
  buildMsel['draw_' + which] = draw;
}
function closeAllMsel(except) { $$('.msel-pop').forEach(function (p) { if (p !== except) p.classList.remove('open'); }); }

/* sorting — 3-state cycle desc -> asc -> default(net desc) */
function cycleSort(col) {
  if (state.sortCol !== col) { state.sortCol = col; state.sortDir = 'desc'; }
  else if (state.sortDir === 'desc') { state.sortDir = 'asc'; }
  else { state.sortCol = 'net'; state.sortDir = 'desc'; }
  renderInstTable();
}
function markSort() {
  $$('#instTable thead th.sortable').forEach(function (th) {
    var on = th.dataset.col === state.sortCol;
    th.classList.toggle('act', on);
    var chev = on ? (state.sortDir === 'desc' ? '▼' : '▲') : '▵';
    var s = th.querySelector('.chev'); if (s) s.textContent = chev;
  });
}

/* tooltips for pooled badge */
var tipEl;
function wireTooltips() {
  if (!tipEl) { tipEl = el('div', 'cvtip'); ROOT.appendChild(tipEl); }
  $$('[data-tip]').forEach(function (n) {
    n.onmouseenter = function () { tipEl.textContent = n.dataset.tip; tipEl.style.display = 'block'; var r = n.getBoundingClientRect(); tipEl.style.left = Math.min(r.left, window.innerWidth - 240) + 'px'; tipEl.style.top = (r.bottom + 6) + 'px'; };
    n.onmouseleave = function () { tipEl.style.display = 'none'; };
  });
}

/* ---------- helpers ---------- */
function amt(v) { return v === 0 ? '<span class="endash">–</span>' : rupee(v); }
function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }
function relTime(iso) {
  if (!iso) return '–';
  var then = new Date(iso), now = new Date();
  var days = Math.floor((now - then) / 86400000);
  if (days <= 0) return 'today'; if (days === 1) return 'yesterday'; return days + 'd ago';
}
function emptyRow(span, t, s) { return '<tr><td colspan="' + span + '"><div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/></svg><div class="t">' + t + '</div><div class="s">' + s + '</div></div></td></tr>'; }

/* clock */
function clock() {
  function tick() {
    var d = new Date();
    var c = $('#clock'); if (c) c.textContent = d.getDate() + ' ' + MO[d.getMonth()] + ' ' + d.getFullYear() + '  ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }
  tick(); setInterval(tick, 1000);
}

/* ---------- markup ---------- */
var BODY =
'<header class="topbar">' +
  '<div class="brand"><div class="logo">R</div><div>' +
    '<div class="ttl">Daily Fee Collection</div>' +
    '<div class="sub">Daily collection and refund activity across the RGI Group</div>' +
  '</div></div>' +
  '<div class="spacer"></div>' +
  '<div class="statpills" id="statpills"></div>' +
  '<div class="tclock mono" id="clock">—</div>' +
'</header>' +
'<div class="filterbar">' +
  '<div class="fgroup"><span class="flabel">Direction</span><div class="seg" id="seg-direction">' +
    '<button data-v="collections">Collections</button><button data-v="refunds">Refunds</button><button data-v="both">Both</button></div></div>' +
  '<div class="fgroup"><span class="flabel">Range</span><div class="seg" id="seg-date">' +
    '<button data-v="yesterday">Yesterday</button><button data-v="week">Week</button><button data-v="month">Month</button><button data-v="fyytd">FY YTD</button><button data-v="custom">Custom</button></div>' +
    '<div class="custom-range" id="customRange"><input type="date" id="cstart"><span class="dim">to</span><input type="date" id="cend"></div></div>' +
  '<div class="fgroup"><span class="flabel">Trust group</span><div class="msel" id="msel-group">' +
    '<button class="msel-btn"><span class="label">All</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="6 9 12 15 18 9"/></svg></button>' +
    '<div class="msel-pop"><div class="msel-list"></div><div class="mtools"><button class="selall">Select all</button><button class="clr">Clear</button></div></div></div></div>' +
  '<div class="fgroup"><span class="flabel">Institution</span><div class="msel" id="msel-inst">' +
    '<button class="msel-btn"><span class="label">All</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="6 9 12 15 18 9"/></svg></button>' +
    '<div class="msel-pop"><input class="search" placeholder="Search 18 institutions…"><div class="msel-list"></div><div class="mtools"><button class="selall">Select all</button><button class="clr">Clear</button></div></div></div></div>' +
  '<div class="fgroup"><span class="flabel">Channel</span><div class="seg" id="seg-channel">' +
    '<button data-v="all">All</button><button data-v="bank">Bank</button><button data-v="cash">Cash</button></div></div>' +
  '<div class="fgroup"><span class="flabel">Status</span><div class="seg" id="seg-status">' +
    '<button data-v="active">Active</button><button data-v="cancelled">Cancelled</button><button data-v="both">Both</button></div></div>' +
  '<div class="fgroup"><span class="flabel">Source</span><div class="seg" id="seg-source">' +
    '<button data-v="all">All</button><button data-v="live">Live</button><button data-v="historical">Historical</button></div></div>' +
  '<a class="clearall">Clear all</a>' +
'</div>' +
'<main class="page">' +
  '<section class="summary cvfade" id="summary"></section>' +
  '<section class="card cvfade"><div class="card-h"><h3>Daily activity</h3><span class="hint">Green collections · amber refunds (below axis) · blue net · click a bar to drill the day</span></div><div class="chartwrap"><canvas id="dailyChart"></canvas></div></section>' +
  '<section class="card cvfade" id="instCard"><div class="card-h"><h3>By institution</h3><span class="hint">Click a row to expand its ledgers &amp; mini-trend</span></div>' +
    '<table id="instTable"><thead><tr><th>CV Code</th><th>Company</th><th>Trust group</th>' +
    '<th class="r sortable" data-col="c">Collections<span class="chev">▵</span></th>' +
    '<th class="r sortable" data-col="r">Refunds<span class="chev">▵</span></th>' +
    '<th class="r sortable" data-col="net">Net<span class="chev">▼</span></th>' +
    '<th class="sortable" data-col="n">JEs<span class="chev">▵</span></th>' +
    '<th class="sortable" data-col="last">Last activity<span class="chev">▵</span></th>' +
    '</tr></thead><tbody id="instBody"></tbody></table></section>' +
  '<section class="card cvfade"><div class="card-h"><h3>Bank ledger throughflow</h3><span class="hint">Fixed windows · click a row for every JE that touched the ledger</span></div>' +
    '<table><thead><tr><th>Company</th><th>Bank ledger</th><th class="r">Yesterday</th><th class="r">This week</th><th class="r">This month</th><th>14-day</th></tr></thead><tbody id="flowBody"></tbody></table></section>' +
  '<section class="card cvfade" id="feedCard"><div class="card-h"><h3>Recent activity</h3></div>' +
    '<div class="feedgrid"><div class="left"><div class="feedhead"><span id="feedHead">Recent activity</span> · <span id="feedSub" class="dim"></span></div><div class="timeline" id="timeline"></div></div>' +
    '<div class="right"><div class="searchpanel"><input class="ref" id="refsearch" placeholder="Search by CyberVidya reference…">' +
      '<div class="ex">e.g. CV-GHRCE-ICICI773-20260527 · HIST-GHRJCJ-773-20260420</div><div class="recent-chips" id="recentChips"></div>' +
      '<div class="searchresult">Exact reference opens the entry. A prefix or partial match filters the timeline on the left.</div></div></div></div></section>' +
  '<footer class="foot"><div class="u"><b style="color:var(--tx2)">CyberVidya → ERPNext v16</b> · fee collection &amp; refunds</div><div class="p">Powered by <b>Dux DigiTech</b></div></footer>' +
'</main>' +
'<div class="scrim" id="scrim"></div>' +
'<aside class="drawer" id="drawer"></aside>';

/* ---------- boot ---------- */
function boot() {
  wireSegments(); wireCustom();
  buildMsel('group', GROUPS.map(function (g) { return { key: g.key, name: g.name, n: g.n }; }), false);
  buildMsel('inst', INST.map(function (i) { return { key: i.code, name: i.code, group: i.groupName }; }), true);
  $('#refsearch').addEventListener('keydown', function (e) { if (e.key === 'Enter') doSearch(e.target.value); });
  $('#refsearch').addEventListener('input', function (e) { if (!e.target.value) { state.search = ''; call('feed', currentFilters()).then(renderFeed); } });
  $('.clearall').onclick = function () { state.direction = 'both'; state.dateKey = 'yesterday'; state.groups = []; state.insts = []; state.channel = 'all'; state.status = 'active'; state.source = 'all'; state.expandedCode = null; if (buildMsel.draw_group) buildMsel.draw_group(); if (buildMsel.draw_inst) buildMsel.draw_inst(); renderAll(); };
  $('#scrim').onclick = closeDrawer;
  $$('#instTable thead th.sortable').forEach(function (th) { th.onclick = function () { cycleSort(th.dataset.col); }; });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeDrawer(); closeAllMsel(null); } });
  document.addEventListener('click', function () { closeAllMsel(null); });
  clock();
  renderAll();
}

return {
  init: function (rootEl) {
    ROOT = rootEl;
    rootEl.classList.add('dux-cv-dash');
    rootEl.innerHTML = BODY;
    boot();
  },
};
})();
