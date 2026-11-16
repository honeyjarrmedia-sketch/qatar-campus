/* Qatar Campus: one-page records browser. No dependencies.
   All text that comes from the data is inserted with textContent. */
(function () {
  'use strict';

  var FEATURED = [['QA', 'Qatar'], ['CN', 'China'], ['RU', 'Russia'], ['SA', 'Saudi Arabia'], ['TR', 'Turkey']];
  var PAGE_SIZE = 25;
  var CONN_PAGE = 10;
  var $ = function (id) { return document.getElementById(id); };
  var fmt = new Intl.NumberFormat('en-US');
  var money = function (n) { return '$' + fmt.format(Math.round(n)); };
  var compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
  // Headline figures: a short form for reading, with the exact figure beneath.
  var bigMoney = function (n) {
    var a = Math.abs(n);
    if (a >= 1e9) return '$' + (n / 1e9).toFixed(2) + ' billion';
    if (a >= 1e6) return '$' + (n / 1e6).toFixed(1) + ' million';
    return money(n);
  };

  var rows = [];            // decoded records currently loaded
  var meta = null;          // year_min, year_max, other_countries
  var otherLoaded = false;
  var otherLoading = null;
  var connections = [];
  var connShown = CONN_PAGE;
  var openRow = '';

  var state = { c: 'QA', from: null, to: null, q: '', type: '', min: '', conf: '', sup: true,
                ent: '', row: '', m: 'auto', sort: 'year', dir: -1, page: 0 };

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'class') n.className = attrs[k];
      else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (k) { if (k) n.appendChild(typeof k === 'string' ? document.createTextNode(k) : k); });
    return n;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  // ---- Data -------------------------------------------------------------
  function decode(pack) {
    var f = pack.fields, d = pack.dict, out = [];
    for (var i = 0; i < pack.rows.length; i++) {
      var a = pack.rows[i], o = {};
      for (var j = 0; j < f.length; j++) {
        var v = a[j];
        o[f[j]] = (d[f[j]] && v !== null) ? d[f[j]][v] : v;
      }
      o._s = ((o.entity || '') + ' ' + (o.principal || '') + ' ' + (o.client || '')).toLowerCase();
      out.push(o);
    }
    return out;
  }
  function getJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(url + ' returned ' + r.status);
      return r.json();
    });
  }
  function needOther() { return state.c === 'ALL' || state.c.slice(0, 2) === 'X:' || !!state.ent; }
  function loadOther() {
    if (otherLoaded) return Promise.resolve();
    if (!otherLoading) {
      setStatus('Loading records for all countries…');
      otherLoading = getJSON('data/other.json').then(function (pack) {
        rows = rows.concat(decode(pack));
        otherLoaded = true;
      });
    }
    return otherLoading;
  }

  // ---- Filtering ----------------------------------------------------------
  function fullRange() { return state.from === meta.year_min && state.to === meta.year_max; }
  function inYears(r, from, to, full) {
    if (r.year === null) return full;
    if (r.t === 'fara') {
      var end = r.yearEnd === null ? meta.year_max : r.yearEnd;
      return r.year <= to && end >= from;
    }
    return r.year >= from && r.year <= to;
  }
  function inCountry(r) {
    if (state.ent) return r.eid === state.ent;
    if (state.c === 'ALL') return true;
    if (state.c.slice(0, 2) === 'X:') return r.country === state.c.slice(2);
    return r.cc === state.c;
  }
  function scopeRows() {
    var full = fullRange();
    return rows.filter(function (r) { return inCountry(r) && inYears(r, state.from, state.to, full); });
  }
  function tableRows(scope) {
    var q = state.q.trim().toLowerCase();
    var min = state.min === '' ? null : Number(state.min);
    var out = scope.filter(function (r) {
      if (state.sup && r.sup) return false;
      if (state.type && r.t !== state.type) return false;
      if (state.conf && r.conf !== state.conf) return false;
      if (min !== null && !(r.amount !== null && r.amount >= min)) return false;
      if (q && r._s.indexOf(q) === -1) return false;
      return true;
    });
    var key = state.sort, dir = state.dir;
    var get = {
      country: function (r) { return r.country; }, type: function (r) { return r.t; },
      entity: function (r) { return r.entity; }, principal: function (r) { return r.principal || r.client || ''; },
      amount: function (r) { return r.amount; }, year: function (r) { return r.year; },
      conf: function (r) { return r.conf; }
    }[key];
    out.sort(function (a, b) {
      var x = get(a), y = get(b);
      if (x === null || x === undefined) return (y === null || y === undefined) ? 0 : 1;  // empty values last
      if (y === null || y === undefined) return -1;
      if (x < y) return -dir;
      if (x > y) return dir;
      return a.id < b.id ? -1 : 1;
    });
    return out;
  }
  // A lobbying filing linked to two featured countries is two rows. When
  // several countries are in view it must still be counted once.
  function filingKey(r) { return r.id.slice(4, r.id.lastIndexOf('-')); }
  function uniqueFilings(list) {
    var seen = {}, out = [];
    list.forEach(function (r) {
      if (r.t !== 'lda' || r.sup) return;
      var k = filingKey(r);
      if (!seen[k]) { seen[k] = 1; out.push(r); }
    });
    return out;
  }

  // ---- Totals -------------------------------------------------------------
  function scopeName() {
    if (state.ent) {
      var hit = rows.find(function (r) { return r.eid === state.ent; });
      return hit ? hit.entity : 'Selected organization';
    }
    if (state.c === 'ALL') return 'All countries';
    if (state.c.slice(0, 2) === 'X:') return state.c.slice(2);
    return FEATURED.filter(function (f) { return f[0] === state.c; })[0][1];
  }
  function renderTotals(scope) {
    var fara = scope.filter(function (r) { return r.t === 'fara'; });
    var regs = {}, princ = {};
    fara.forEach(function (r) { regs[r.eid] = 1; princ[(r.principal || '').toUpperCase()] = 1; });
    var filings = uniqueFilings(scope);
    var income = 0, incomeN = 0, expenses = 0, expensesN = 0;
    filings.forEach(function (r) {
      if (r.amount === null) return;
      if ((r.amtType || '').indexOf('income') === 0) { income += r.amount; incomeN++; }
      else if ((r.amtType || '').indexOf('expenses') === 0) { expenses += r.amount; expensesN++; }
    });
    var uni = scope.filter(function (r) { return r.t === 'sec117'; });
    var uniTotal = 0; uni.forEach(function (r) { uniTotal += r.amount || 0; });
    var tiles = [
      ['University gifts and contracts reported', bigMoney(uniTotal), 'Show the ' + fmt.format(uni.length) + ' reports', 'sec117', uniTotal],
      ['FARA registrants', fmt.format(Object.keys(regs).length), 'Show the registrations', 'fara', null],
      ['Foreign principals', fmt.format(Object.keys(princ).length), 'Show the registrations', 'fara', null],
      ['Lobbying filings', fmt.format(filings.length), 'Show the filings', 'lda', null],
      ['Lobbying income reported', bigMoney(income), 'Show the ' + fmt.format(incomeN) + ' filings with income', 'lda', income]
    ];
    var box = $('stats');
    clear(box);
    tiles.forEach(function (t) {
      box.appendChild(el('div', { 'class': 'card stat' }, [
        el('div', { 'class': 'label', text: t[0] }),
        el('div', { 'class': 'stat-value', text: t[1] }),
        (t[4] !== null && Math.abs(t[4]) >= 1e6) ? el('div', { 'class': 'stat-exact', text: money(t[4]) + ' exactly' }) : null,
        el('div', { 'class': 'stat-foot' }, [
          el('button', { type: 'button', 'class': 'linklike', text: t[2], onclick: function () {
            state.type = t[3]; $('f-type').value = t[3]; state.page = 0; update();
            $('records').scrollIntoView();
          } }),
          el('span', { 'class': 'tag tag-derived', text: 'derived' })
        ])
      ]));
    });
    var note = 'Totals are marked derived because they are counted from individual records. ' +
      'The Justice Department bulk file carries no dollar amounts, so FARA fees appear only where they have been read from a registrant\'s supplemental statement. ' +
      'Lobbying filings and university reports are included for Qatar, China, Russia, Saudi Arabia and Turkey only. ' +
      'University reports cover gifts and contracts that institutions reported to the Department of Education through February 28, 2025.';
    if (expensesN) note += ' Separately, ' + fmt.format(expensesN) + ' filings by organizations lobbying on their own behalf report ' + money(expenses) + ' in expenses; that figure covers all of the organization\'s lobbying.';
    $('stats-note').textContent = note;
    $('scope-label').textContent = scopeName() + ', ' + state.from + (state.from === state.to ? '' : ' to ' + state.to);
    var name = scopeName();
    $('heading').textContent = (state.c === 'ALL' && !state.ent)
      ? 'Foreign principals in United States disclosure records'
      : state.ent ? 'Records on file for ' + name
      : name + ' in United States disclosure records';
  }

  // ---- Chart --------------------------------------------------------------
  var MEASURES = {
    fara: { unit: 'FARA registrations active', money: false },
    lda: { unit: 'lobbying filings', money: false },
    income: { unit: 'in lobbying income reported', money: true },
    uni: { unit: 'in university gifts and contracts reported', money: true }
  };
  // Until the visitor picks a measure, show university dollars where the
  // selection has university reports and FARA registrations otherwise.
  function measure(scope) {
    if (state.m !== 'auto') return state.m;
    return scope.some(function (r) { return r.t === 'sec117'; }) ? 'uni' : 'fara';
  }
  function chartSeries(scope, m) {
    var from = state.from, to = state.to, out = [], y;
    var byYear = {};
    if (m === 'fara') {
      scope.forEach(function (r) {
        if (r.t !== 'fara' || r.year === null) return;
        var end = r.yearEnd === null ? meta.year_max : r.yearEnd;
        for (var yy = Math.max(r.year, from); yy <= Math.min(end, to); yy++) byYear[yy] = (byYear[yy] || 0) + 1;
      });
    } else if (m === 'uni') {
      scope.forEach(function (r) {
        if (r.t === 'sec117' && r.year !== null && r.amount !== null) byYear[r.year] = (byYear[r.year] || 0) + r.amount;
      });
    } else {
      uniqueFilings(scope).forEach(function (r) {
        if (r.year === null) return;
        if (m === 'lda') byYear[r.year] = (byYear[r.year] || 0) + 1;
        else if (r.amount !== null && (r.amtType || '').indexOf('income') === 0) byYear[r.year] = (byYear[r.year] || 0) + r.amount;
      });
    }
    for (y = from; y <= to; y++) out.push([y, byYear[y] || 0]);
    // Trim empty years at the start so a long empty history does not flatten the chart.
    var first = 0;
    while (first < out.length - 1 && out[first][1] === 0) first++;
    return out.slice(first);
  }
  function niceStep(v, whole) {
    if (v <= 0) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
    var step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
    return whole ? Math.max(1, Math.round(step)) : step;
  }
  function svg(tag, attrs) {
    var n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function renderChart(scope) {
    var mk = measure(scope), series = chartSeries(scope, mk), box = $('chart'), tip = $('chart-tip'), m = MEASURES[mk];
    $('measure').value = mk;
    clear(box); tip.hidden = true;
    var max = Math.max.apply(null, series.map(function (s) { return s[1]; }));
    var label = function (v) { return m.money ? money(v) : fmt.format(v); };
    // Table view: always available, carries every value.
    var tb = el('table', null, [el('thead', null, [el('tr', null, [el('th', { scope: 'col', text: 'Year' }), el('th', { scope: 'col', text: m.money ? 'USD' : 'Count' })])])]);
    var body = el('tbody');
    series.forEach(function (s) { body.appendChild(el('tr', null, [el('td', { text: String(s[0]) }), el('td', { text: label(s[1]) })])); });
    tb.appendChild(body); clear($('chart-table')); $('chart-table').appendChild(tb);
    if (!series.length || max <= 0) {
      box.appendChild(el('p', { 'class': 'chart-empty', text: 'No records of this kind in the selected country and years.' }));
      return;
    }
    var W = 1100, H = 280, L = 64, R = 8, T = 14, B = 30;
    var pw = W - L - R, ph = H - T - B, n = series.length, band = pw / n;
    var bw = Math.max(1, Math.min(24, band - 2));
    var step = niceStep(max / 4, !m.money), ticks = Math.max(1, Math.ceil(max / step)), top = step * ticks;
    var root = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, 'class': 'chart-svg', role: 'img',
      'aria-label': 'Bar chart: ' + m.unit + ' by year for ' + scopeName() + '. The same figures are in the table below.' });
    for (var i = 0; i <= ticks; i++) {
      var v = step * i, yy = T + ph - ph * i / ticks;
      if (i) root.appendChild(svg('line', { x1: L, x2: W - R, y1: yy, y2: yy, 'class': 'grid' }));
      var t = svg('text', { x: L - 8, y: yy + 4, 'text-anchor': 'end' });
      t.textContent = (m.money ? '$' : '') + (top >= 10000 ? compact.format(v) : fmt.format(v));
      root.appendChild(t);
    }
    var every = Math.ceil(n / 14);
    series.forEach(function (s, idx) {
      var x = L + band * idx + (band - bw) / 2, h = ph * s[1] / top, y0 = T + ph;
      if (s[1] > 0) {
        var r = Math.min(4, bw / 2, h);
        var d = 'M' + x + ',' + y0 + ' V' + (y0 - h + r) + ' Q' + x + ',' + (y0 - h) + ' ' + (x + r) + ',' + (y0 - h) +
          ' H' + (x + bw - r) + ' Q' + (x + bw) + ',' + (y0 - h) + ' ' + (x + bw) + ',' + (y0 - h + r) + ' V' + y0 + ' Z';
        root.appendChild(svg('path', { d: d, 'class': 'bar', 'data-i': idx }));
      }
      if (idx % every === 0) {
        var xt = svg('text', { x: L + band * idx + band / 2, y: H - 8, 'text-anchor': 'middle' });
        xt.textContent = String(s[0]);
        root.appendChild(xt);
      }
      var hit = svg('rect', { x: L + band * idx, y: T, width: band, height: ph, 'class': 'hit' });
      hit.addEventListener('pointermove', function () {
        tip.hidden = false; clear(tip);
        tip.appendChild(el('strong', { text: label(s[1]) }));
        tip.appendChild(document.createTextNode(m.unit + ', ' + s[0]));
        var card = box.parentNode.getBoundingClientRect(), g = root.getBoundingClientRect();
        var sx = g.width / W;
        tip.style.left = (g.left - card.left + (L + band * idx + band / 2) * sx) + 'px';
        tip.style.top = (g.top - card.top + (y0 - h) * (g.height / H) - 8) + 'px';
      });
      hit.addEventListener('pointerleave', function () { tip.hidden = true; });
      hit.addEventListener('click', function () { setYears(s[0], s[0]); });
      root.appendChild(hit);
    });
    root.appendChild(svg('line', { x1: L, x2: W - R, y1: T + ph, y2: T + ph, 'class': 'axis' }));
    box.appendChild(root);
  }

  // ---- Records table ------------------------------------------------------
  var KIND = { fara: 'FARA registration', lda: 'LDA filing', sec117: 'University report' };
  var ACTOR = { fara: 'fara_registrant', lda: 'lobbying_registrant', sec117: 'university' };
  function amountCell(r) {
    var td = el('td', { 'class': 'num' });
    if (r.amount !== null) {
      td.appendChild(document.createTextNode(money(r.amount)));
      if (r.amtType) td.appendChild(el('div', { 'class': 'sub', text: r.amtType }));
    } else {
      td.className = 'num none';
      td.textContent = r.t === 'fara' ? 'not in bulk data' : 'none stated';
    }
    return td;
  }
  function yearText(r) {
    if (r.year === null) return 'no date';
    if (r.t !== 'fara') return String(r.year);
    return r.year + '–' + (r.yearEnd === null ? 'present' : r.yearEnd);
  }
  function detailRow(r) {
    var shows = el('div', null, [el('div', { 'class': 'label', text: 'What the filing shows' })]);
    shows.appendChild(el('div', { text: r.role + '.' }));
    if (r.t === 'fara') shows.appendChild(el('div', { text: 'Relationship dates as listed in the Justice Department file: ' + (r.dStart || 'not stated') + ' to ' + (r.dEnd || 'no end date listed') + '.' }));
    else if (r.t === 'lda') shows.appendChild(el('div', { text: r.srcType + (r.period ? ', ' + r.period : '') + ', posted ' + (r.dStart || 'date not stated') + '.' }));
    if (r.client && r.client !== r.principal) shows.appendChild(el('div', { text: 'Client: ' + r.client }));
    if (r.t === 'sec117') {
      shows.appendChild(el('div', { text: 'Transaction type: ' + r.purpose + '.' }));
      if (r.principal) shows.appendChild(el('div', { text: 'Foreign source named in the file: ' + r.principal }));
      if (r.detail) shows.appendChild(el('div', { text: r.detail + '.' }));
    } else {
      if (r.purpose) shows.appendChild(el('div', { text: 'Issue areas listed: ' + r.purpose }));
      if (r.detail) shows.appendChild(el('div', { text: 'Described on the filing as: ' + r.detail }));
    }
    if (r.people) shows.appendChild(el('div', { text: 'Lobbyists named on the filing: ' + r.people }));

    var why = el('div', null, [el('div', { 'class': 'label', text: 'Why this row is listed under ' + r.country }),
      el('div', { text: r.basis + '.' })]);
    if (r.notes) why.appendChild(el('div', { text: r.notes }));

    var src = el('div', null, [el('div', { 'class': 'label', text: 'Source documents' })]);
    [r.url].concat(r.urls || []).forEach(function (u, i) {
      src.appendChild(el('a', { href: u, rel: 'noopener', target: '_blank', text: (i === 0 ? r.srcType : 'Related filing ' + i) + ' (' + u.split('/')[2] + ')' }));
    });
    if (r.t === 'fara') src.appendChild(el('a', { href: 'https://efile.fara.gov/api/v1/RegDocs/html/' + r.eid.slice(5), rel: 'noopener', target: '_blank', text: 'Every document filed under this registration (efile.fara.gov)' }));
    src.appendChild(el('div', { 'class': 'small', text: 'Retrieved ' + r.retrieved }));
    src.appendChild(el('button', { type: 'button', 'class': 'linklike', text: r.t === 'sec117' ? 'Show all records for this institution' : 'Show all records for this registrant', onclick: function () { setEntity(r.eid); } }));
    src.appendChild(el('button', { type: 'button', 'class': 'linklike', text: 'Copy link to this row', onclick: function (e) {
      var link = location.origin + location.pathname + '?c=' + encodeURIComponent(r.cc || r.country) + '&row=' + encodeURIComponent(r.id) + '#records';
      var done = function () { e.target.textContent = 'Link copied'; };
      if (navigator.clipboard) navigator.clipboard.writeText(link).then(done, function () { window.prompt('Copy this link', link); });
      else window.prompt('Copy this link', link);
    } }));
    return el('tr', { 'class': 'detail' }, [el('td', { colspan: '8' }, [el('div', { 'class': 'detail-grid' }, [shows, why, src])])]);
  }
  function renderTable(list) {
    var tbody = $('rows'); clear(tbody);
    var pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
    if (state.page >= pages) state.page = pages - 1;
    var start = state.page * PAGE_SIZE, slice = list.slice(start, start + PAGE_SIZE);
    slice.forEach(function (r) {
      var open = openRow === r.id;
      var tr = el('tr', { id: 'r-' + r.id }, [
        el('td', { text: r.country }),
        el('td', { style: 'font-size: 14px', text: KIND[r.t] }),
        el('td', null, [el('button', { type: 'button', 'class': 'linklike', style: 'font-weight: 500', 'aria-expanded': String(open), text: r.entity,
          onclick: function () { openRow = open ? '' : r.id; state.row = openRow; update(true); } })]),
        el('td', r.principal || r.client ? { text: r.principal || r.client } : { 'class': 'muted', style: 'font-size: 14px', text: r.t === 'sec117' ? 'not named in the file' : '' }),
        amountCell(r),
        el('td', { 'class': 'yr', text: yearText(r) }),
        el('td', null, [el('a', { href: r.url, rel: 'noopener', target: '_blank', style: 'font-size: 14px; white-space: nowrap', text: 'Open filing' })]),
        el('td', null, [el('span', { 'class': 'tag tag-' + r.conf, text: r.conf })])
      ]);
      tbody.appendChild(tr);
      if (open) tbody.appendChild(detailRow(r));
    });
    if (!slice.length) tbody.appendChild(el('tr', null, [el('td', { colspan: '8', 'class': 'muted', text: 'No records match these choices.' })]));
    $('count').textContent = fmt.format(list.length);
    $('page-info').textContent = list.length ? 'Showing ' + fmt.format(start + 1) + '–' + fmt.format(start + slice.length) + ' of ' + fmt.format(list.length) : 'Showing 0 records';
    $('prev').disabled = state.page === 0;
    $('next').disabled = state.page >= pages - 1;
    document.querySelectorAll('table.records th[data-sort]').forEach(function (th) {
      if (th.getAttribute('data-sort') === state.sort) th.setAttribute('aria-sort', state.dir === 1 ? 'ascending' : 'descending');
      else th.removeAttribute('aria-sort');
    });
    var chip = $('entity-chip'); clear(chip);
    if (state.ent) chip.appendChild(el('span', { 'class': 'chip' }, ['Showing only: ' + scopeName(),
      el('button', { type: 'button', text: 'Clear', onclick: function () { setEntity(''); } })]));
  }

  // ---- CSV of the current view -------------------------------------------
  var CSV_COLS = [['id', 'id'], ['country', 'country'], ['actor_type', 't'], ['entity_or_person_name', 'entity'], ['role', 'role'],
    ['foreign_principal', 'principal'], ['amount_usd', 'amount'], ['year', 'year'], ['purpose', 'purpose'], ['source_url', 'url'],
    ['source_type', 'srcType'], ['confidence', 'conf'], ['date_retrieved', 'retrieved'], ['notes', 'notes'],
    ['client_name', 'client'], ['amount_type', 'amtType'], ['year_end', 'yearEnd'], ['date_start', 'dStart'], ['date_end', 'dEnd'],
    ['period', 'period'], ['link_basis', 'basis'], ['superseded', 'sup']];
  function csvCell(v) {
    if (v === null || v === undefined) return '';
    var s = String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;  // stop spreadsheet formula injection
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function downloadCsv(list) {
    var lines = [CSV_COLS.map(function (c) { return c[0]; }).join(',')];
    list.forEach(function (r) {
      lines.push(CSV_COLS.map(function (c) {
        var v = r[c[1]];
        if (c[1] === 't') v = ACTOR[r.t];
        if (c[1] === 'sup') v = r.sup ? 'true' : 'false';
        return csvCell(v);
      }).join(','));
    });
    var blob = new Blob(['﻿' + lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' });
    var a = el('a', { href: URL.createObjectURL(blob), download: 'qatar-campus-records-view.csv' });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  // ---- Connections --------------------------------------------------------
  function renderConnections() {
    var tbody = $('conn-rows'); clear(tbody);
    var names = {}; FEATURED.forEach(function (f) { names[f[0]] = f[1]; });
    connections.slice(0, connShown).forEach(function (c) {
      tbody.appendChild(el('tr', null, [
        el('td', null, [el('button', { type: 'button', 'class': 'linklike', style: 'font-weight: 500', text: c.name, onclick: function () { setEntity(c.eid); $('records').scrollIntoView(); } }),
          el('div', { 'class': 'sub', text: c.source === 'Section 117' ? 'Institution reporting under Section 117' : c.source + ' registrant' })]),
        el('td', { text: c.cc.map(function (x) { return names[x] || x; }).join(', ') }),
        el('td', { 'class': 'yr', text: c.all === null ? 'not known for lobbying filings' : c.cc.length + ' of ' + c.all }),
        el('td', null, [el('button', { type: 'button', 'class': 'linklike', style: 'font-size: 14px', text: 'Show the ' + fmt.format(c.n) + ' records', onclick: function () { setEntity(c.eid); $('records').scrollIntoView(); } })]),
        el('td', null, [el('span', { 'class': 'tag tag-derived', text: 'derived' })])
      ]));
    });
    if (!connections.length) tbody.appendChild(el('tr', null, [el('td', { colspan: '5', 'class': 'muted', text: 'No registrant has records in more than one featured country.' })]));
    $('conn-info').textContent = connections.length ? 'Showing ' + Math.min(connShown, connections.length) + ' of ' + fmt.format(connections.length) + ' registrants' : '';
    $('conn-more').hidden = connShown >= connections.length;
  }

  // ---- State, URL and wiring ---------------------------------------------
  function setStatus(t) { $('status').textContent = t; }
  function setYears(a, b) {
    a = Math.max(meta.year_min, Math.min(meta.year_max, a)); b = Math.max(meta.year_min, Math.min(meta.year_max, b));
    if (a > b) { var t = a; a = b; b = t; }
    $('y-from').value = a; $('y-to').value = b;
    // Nothing changed: do not redraw, or a click already in progress on the
    // chart or table would be lost when its target is replaced.
    if (a === state.from && b === state.to) return;
    state.from = a; state.to = b; state.page = 0; update();
  }
  function setEntity(eid) { state.ent = eid; state.page = 0; openRow = ''; state.row = ''; update(); }
  function writeUrl() {
    var p = new URLSearchParams();
    if (state.c !== 'QA') p.set('c', state.c.slice(0, 2) === 'X:' ? state.c.slice(2) : state.c);
    if (state.from !== meta.year_min) p.set('from', state.from);
    if (state.to !== meta.year_max) p.set('to', state.to);
    ['q', 'type', 'min', 'conf', 'ent', 'row'].forEach(function (k) { if (state[k]) p.set(k, state[k]); });
    if (!state.sup) p.set('sup', '0');
    if (state.m !== 'auto') p.set('m', state.m);
    var qs = p.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
  }
  function readUrl() {
    var p = new URLSearchParams(location.search), c = p.get('c');
    if (c) state.c = (c === 'ALL' || FEATURED.some(function (f) { return f[0] === c; })) ? c : 'X:' + c;
    var n = function (k, d) { var v = parseInt(p.get(k), 10); return isNaN(v) ? d : v; };
    state.from = Math.max(meta.year_min, Math.min(meta.year_max, n('from', meta.year_min)));
    state.to = Math.max(meta.year_min, Math.min(meta.year_max, n('to', meta.year_max)));
    ['q', 'type', 'min', 'conf', 'ent', 'row'].forEach(function (k) { if (p.get(k)) state[k] = p.get(k); });
    if (p.get('sup') === '0') state.sup = false;
    if (MEASURES[p.get('m')]) state.m = p.get('m');
    openRow = state.row;
  }
  function syncControls() {
    document.querySelectorAll('#tabs .tab').forEach(function (b) {
      b.setAttribute('aria-pressed', String(!state.ent && b.getAttribute('data-c') === state.c));
    });
    $('more-countries').value = state.c.slice(0, 2) === 'X:' ? state.c.slice(2) : '';
    $('y-from').value = state.from; $('y-to').value = state.to;
    $('q').value = state.q; $('f-type').value = state.type; $('f-min').value = state.min;
    $('f-conf').value = state.conf; $('f-sup').checked = state.sup;
  }
  var lastList = [];
  function update(keepScroll) {
    if (needOther() && !otherLoaded) {
      loadOther().then(function () { update(keepScroll); }, function (e) { setStatus('Could not load all countries: ' + e.message); });
      return;
    }
    var scope = scopeRows();
    lastList = tableRows(scope);
    if (state.row && !keepScroll) {           // arriving on a link to one row
      var idx = lastList.findIndex(function (r) { return r.id === state.row; });
      if (idx < 0 && state.sup) {             // the linked row may be a replaced report
        state.sup = false; lastList = tableRows(scope);
        idx = lastList.findIndex(function (r) { return r.id === state.row; });
        if (idx < 0) { state.sup = true; lastList = tableRows(scope); }
      }
      if (idx >= 0) state.page = Math.floor(idx / PAGE_SIZE);
    }
    syncControls(); renderTotals(scope); renderChart(scope); renderTable(lastList);
    setStatus(fmt.format(lastList.length) + ' records shown');
    writeUrl();
  }
  function wire() {
    document.querySelectorAll('#tabs .tab').forEach(function (b) {
      b.addEventListener('click', function () { state.c = b.getAttribute('data-c'); state.ent = ''; state.page = 0; update(); });
    });
    var sel = $('more-countries');
    (meta.other_countries || []).forEach(function (c) { sel.appendChild(el('option', { value: c[0], text: c[0] + ' (' + fmt.format(c[1]) + ')' })); });
    sel.addEventListener('change', function () { if (sel.value) { state.c = 'X:' + sel.value; state.ent = ''; state.page = 0; update(); } });
    var years = function () { setYears(parseInt($('y-from').value, 10) || meta.year_min, parseInt($('y-to').value, 10) || meta.year_max); };
    $('y-from').addEventListener('change', years); $('y-to').addEventListener('change', years);
    var yt;
    var typed = function () {               // apply a complete year as soon as it is typed
      clearTimeout(yt);
      if (/^\d{4}$/.test($('y-from').value) && /^\d{4}$/.test($('y-to').value)) yt = setTimeout(years, 350);
    };
    $('y-from').addEventListener('input', typed); $('y-to').addEventListener('input', typed);
    $('y-reset').addEventListener('click', function () { setYears(meta.year_min, meta.year_max); });
    var timer;
    $('q').addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(function () { state.q = $('q').value; state.page = 0; update(); }, 200); });
    [['f-type', 'type'], ['f-min', 'min'], ['f-conf', 'conf']].forEach(function (p) {
      $(p[0]).addEventListener('change', function () { state[p[1]] = $(p[0]).value; state.page = 0; update(); });
    });
    $('f-sup').addEventListener('change', function () { state.sup = $('f-sup').checked; state.page = 0; update(); });
    $('measure').addEventListener('change', function () { state.m = $('measure').value; update(true); });
    $('prev').addEventListener('click', function () { if (state.page > 0) { state.page--; update(true); $('records').scrollIntoView(); } });
    $('next').addEventListener('click', function () { state.page++; update(true); $('records').scrollIntoView(); });
    $('csv-view').addEventListener('click', function () { downloadCsv(lastList); });
    $('conn-more').addEventListener('click', function () { connShown += CONN_PAGE; renderConnections(); });
    document.querySelectorAll('table.records th[data-sort]').forEach(function (th) {
      th.querySelector('button').addEventListener('click', function () {
        var k = th.getAttribute('data-sort');
        if (state.sort === k) state.dir = -state.dir; else { state.sort = k; state.dir = (k === 'year' || k === 'amount') ? -1 : 1; }
        state.page = 0; update(true);
      });
    });
  }

  getJSON('data/featured.json').then(function (pack) {
    meta = { year_min: pack.year_min, year_max: pack.year_max, other_countries: pack.other_countries };
    rows = decode(pack);
    readUrl(); wire(); update();
    if (state.row) { var t = document.getElementById('r-' + state.row); if (t) t.scrollIntoView(); }
    return getJSON('data/connections.json');
  }).then(function (c) { connections = c; renderConnections(); })
    .catch(function (e) { setStatus('The records could not be loaded (' + e.message + '). The full CSV file is still available from the link at the top of the page.'); });
})();
