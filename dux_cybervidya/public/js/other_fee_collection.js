/* Other Fees / Sanstha Collection — dashboard front-end.
   Read-only report served by dux_cybervidya.api.other_fees_dashboard.
   Namespaced under .dux-of-dash. Audit drill-down + drawers + exports +
   light trends; drawer/expand/spark CSS is shared from the daily dashboard. */
(function () {
	"use strict";

	var ROOT = null;
	var CHARTS = {};                 // canvas id -> Chart instance
	var OPTS = { sansthas: [], institutions: [] };
	var DATA = {};                   // last results, so partial re-renders skip refetch
	var state = {
		date_from: "2026-04-01",
		date_to: frappe.datetime.get_today(),
		channel: "all",              // all | bank | cash
		source: "all",               // all | live | historical
		status: "active",            // active | cancelled | both
		sansthas: [],
		institutions: [],
		q: "",
		granularity: "day",          // day | week | month
		expanded: null,              // { kind: 'sanstha'|'college', key }
	};

	var INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
	function money(n) { return "₹" + INR.format(n || 0); }
	function shortMoney(n) {
		n = n || 0; var a = Math.abs(n);
		if (a >= 1e7) return "₹" + (n / 1e7).toFixed(2) + "Cr";
		if (a >= 1e5) return "₹" + (n / 1e5).toFixed(1) + "L";
		if (a >= 1e3) return "₹" + Math.round(n / 1e3) + "k";
		return "₹" + n;
	}
	function esc(s) { return frappe.utils.escape_html(s == null ? "" : String(s)); }
	function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : (s || ""); }
	var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
	function fmtDate(iso) {            // 'YYYY-MM-DD' -> Indian 'DD-MM-YYYY'
		if (!iso) return "";
		var p = String(iso).slice(0, 10).split("-");
		return p.length === 3 ? p[2] + "-" + p[1] + "-" + p[0] : String(iso);
	}
	function ddmm(iso) { var p = String(iso).slice(0, 10).split("-"); return p.length === 3 ? p[2] + "-" + p[1] : String(iso); }
	function fmtMonth(ym) { var p = String(ym).split("-"); return p.length >= 2 ? (MON[(+p[1]) - 1] + " " + p[0]) : String(ym); }
	function prettyDT(dt) { if (!dt) return ""; var s = String(dt); return fmtDate(s.slice(0, 10)) + " " + s.slice(11, 16); }
	function $(sel) { return ROOT.querySelector(sel); }

	function call(method, extra, flt) {
		var args = Object.assign({ filters: JSON.stringify(flt || state) }, extra || {});
		return frappe.call({
			method: "dux_cybervidya.api.other_fees_dashboard." + method,
			args: args,
		}).then(function (r) { return r.message; });
	}
	function scoped(extra) { return Object.assign({}, state, extra || {}); }
	function mkChart(id, config) {
		if (CHARTS[id]) { CHARTS[id].destroy(); delete CHARTS[id]; }
		var cv = $("#" + id); if (!cv) return;
		CHARTS[id] = new Chart(cv.getContext("2d"), config);
	}

	// -------------------------------------------------------------- skeleton
	var BODY = '' +
		'<div class="topbar">' +
		'  <div class="brand"><div class="logo">OF</div>' +
		'    <div><div class="ttl">Other Fees / Sanstha Collection</div>' +
		'    <div class="sub">CyberVidya head-wise fees → sanstha income</div></div></div>' +
		'  <div class="spacer"></div><div class="statpills" id="ofpills"></div>' +
		'  <button id="ofpdf" class="acionbtn" style="margin-left:12px;height:30px;padding:0 12px;border:1px solid var(--bd);border-radius:7px;background:var(--surface2);font-size:12px;cursor:pointer">⤓ PDF</button>' +
		'</div>' +
		'<div class="filterbar" id="offilters"></div>' +
		'<div class="page">' +
		'  <div class="summary cvfade" id="ofsummary"></div>' +
		'  <div class="card"><div class="card-h"><h3>Collections trend</h3>' +
		'     <div style="display:flex;align-items:center;gap:10px"><span class="hint" id="ofchart-hint"></span>' +
		'       <div class="seg" id="ofgran"></div></div></div>' +
		'     <div class="chartwrap"><canvas id="ofchart"></canvas></div></div>' +
		'  <div class="card"><div class="card-h"><h3>By sanstha</h3>' +
		'     <button class="csvbtn" data-csv="sanstha" style="border:0;background:none;color:var(--accent);font-size:11.5px;cursor:pointer">⤓ CSV</button></div>' +
		'     <div class="cvfade" id="ofsanstha"></div></div>' +
		'  <div class="card"><div class="card-h"><h3>By fee head</h3>' +
		'     <button class="csvbtn" data-csv="head" style="border:0;background:none;color:var(--accent);font-size:11.5px;cursor:pointer">⤓ CSV</button></div>' +
		'     <div class="cvfade" id="ofhead"></div></div>' +
		'  <div class="card"><div class="card-h"><h3>By college — reconciliation</h3>' +
		'     <div style="display:flex;gap:12px;align-items:center"><span class="hint">live vs historical, recovered from the JE reference</span>' +
		'       <button class="csvbtn" data-csv="college" style="border:0;background:none;color:var(--accent);font-size:11.5px;cursor:pointer">⤓ CSV</button></div></div>' +
		'     <div class="cvfade" id="ofcollege"></div></div>' +
		'  <div class="card"><div class="card-h"><h3>Recent activity</h3>' +
		'     <span class="hint">click any entry to open it</span></div>' +
		'     <div class="cvfade" id="offeed"></div></div>' +
		'  <div class="foot"><div class="p">Dux CyberVidya • other-fees report</div>' +
		'     <div class="p" id="offoot"></div></div>' +
		'</div>' +
		'<div class="scrim" id="ofscrim"></div><div class="drawer" id="ofdrawer"></div>';

	// -------------------------------------------------------------- filters
	function seg(label, key, opts) {
		var btns = opts.map(function (o) {
			return '<button data-k="' + key + '" data-v="' + o[0] + '"' +
				(state[key] === o[0] ? ' class="on"' : '') + '>' + o[1] + '</button>';
		}).join("");
		return '<div class="fgroup"><span class="flabel">' + label + '</span>' +
			'<div class="seg">' + btns + '</div></div>';
	}
	function chipRow(label, key, items) {
		var chips = items.map(function (it) {
			var on = state[key].indexOf(it.val) >= 0;
			return '<button class="seg-chip' + (on ? ' on" ' : '" ') +
				'data-chipkey="' + key + '" data-chipval="' + esc(it.val) + '">' + esc(it.text) + '</button>';
		}).join("");
		if (!items.length) return "";
		return '<div class="fgroup"><span class="flabel">' + label + '</span>' +
			'<div class="seg" style="flex-wrap:wrap;max-width:520px">' + chips + '</div></div>';
	}
	function renderFilters() {
		var bar = $("#offilters");
		var instItems = OPTS.institutions.map(function (i) { return { val: i.code, text: i.code }; });
		var sanItems = OPTS.sansthas.map(function (s) { return { val: s.company, text: s.abbr || s.company }; });
		bar.innerHTML =
			'<div class="fgroup"><span class="flabel">From</span><input type="date" id="offrom" value="' + state.date_from + '"></div>' +
			'<div class="fgroup"><span class="flabel">To</span><input type="date" id="ofto" value="' + state.date_to + '"></div>' +
			seg("Channel", "channel", [["all", "All"], ["bank", "Bank"], ["cash", "Cash"]]) +
			seg("Source", "source", [["all", "All"], ["live", "Live"], ["historical", "Historical"]]) +
			seg("Status", "status", [["active", "Active"], ["cancelled", "Cancelled"], ["both", "Both"]]) +
			chipRow("Sanstha", "sansthas", sanItems) +
			chipRow("College", "institutions", instItems) +
			'<div class="fgroup"><input type="text" id="ofq" placeholder="ref contains…" value="' + esc(state.q) +
			'" style="height:30px;border:1px solid var(--bd);border-radius:7px;padding:0 9px;font-size:12px"></div>' +
			'<span class="clearall show" id="ofclear">Reset</span>';

		$("#offrom").onchange = function (e) { state.date_from = e.target.value; refresh(); };
		$("#ofto").onchange = function (e) { state.date_to = e.target.value; refresh(); };
		$("#ofq").onkeydown = function (e) { if (e.key === "Enter") { state.q = e.target.value.trim(); refresh(); } };
		bar.querySelectorAll(".seg button[data-k]").forEach(function (b) {
			b.onclick = function () { state[b.dataset.k] = b.dataset.v; state.expanded = null; renderFilters(); refresh(); };
		});
		bar.querySelectorAll(".seg-chip").forEach(function (b) {
			b.onclick = function () {
				var k = b.dataset.chipkey, v = b.dataset.chipval, arr = state[k], i = arr.indexOf(v);
				if (i >= 0) arr.splice(i, 1); else arr.push(v);
				state.expanded = null; renderFilters(); refresh();
			};
		});
		$("#ofclear").onclick = function () {
			state.channel = state.source = "all"; state.status = "active";
			state.sansthas = []; state.institutions = []; state.q = ""; state.expanded = null;
			renderFilters(); refresh();
		};
	}

	// -------------------------------------------------------------- summary + deltas
	function loading(on) { ROOT.querySelectorAll(".cvfade").forEach(function (e) { e.classList.toggle("loading", !!on); }); }
	function deltaBadge(cur, prev) {
		if (prev == null) return "";
		if (!prev) return cur ? '<span style="color:var(--collect);font-size:11px">▲ new</span>' : "";
		var pct = Math.round(((cur - prev) / prev) * 100);
		if (pct === 0) return '<span style="color:var(--tx3);font-size:11px">→ 0%</span>';
		var up = pct > 0;
		return '<span style="color:' + (up ? "var(--collect)" : "var(--cancel)") + ';font-size:11px">' +
			(up ? "▲ " : "▼ ") + Math.abs(pct) + "% vs prev</span>";
	}
	function sumcard(cls, k, v, m, extra) {
		return '<div class="sumcard ' + cls + '"' + (extra || "") + '><div class="k">' + k + '</div>' +
			'<div class="v">' + v + '</div><div class="m">' + (m || "") + '</div></div>';
	}
	function renderSummary(s, prev) {
		$("#ofsummary").innerHTML =
			sumcard("c", "Total collected", money(s.total),
				s.count + " JEs • " + s.sansthas + " sansthas • " + s.colleges + " colleges " + deltaBadge(s.total, prev && prev.total)) +
			sumcard("n", "Bank", money(s.bank.total), s.bank.count + " JEs " + deltaBadge(s.bank.total, prev && prev.bank.total)) +
			sumcard("r", "Cash", money(s.cash.total), s.cash.count + " JEs " + deltaBadge(s.cash.total, prev && prev.cash.total)) +
			sumcard("x", "Cancelled", money(s.cancelled.total), s.cancelled.count + " JEs (click to view)",
				' data-canc="1" style="cursor:pointer"');
		var cx = $('#ofsummary [data-canc]');
		if (cx) cx.onclick = function () { state.status = "cancelled"; renderFilters(); refresh(); };
		$("#ofpills").innerHTML = '<span class="statpill amber"><span class="dot"></span>Live ' +
			shortMoney(s.live.total) + ' • Historical ' + shortMoney(s.historical.total) + '</span>';
	}

	// -------------------------------------------------------------- trend chart (bucketed)
	function weekMonday(ds) { var d = new Date(ds + "T00:00:00"); var off = (d.getDay() + 6) % 7; d.setDate(d.getDate() - off); return d.toISOString().slice(0, 10); }
	function bucketDaily(daily, gran) {
		if (gran === "day") return daily.map(function (r) { return { label: ddmm(r.date), total: r.total }; });
		var map = {};
		daily.forEach(function (r) {
			var k = gran === "week" ? weekMonday(r.date) : r.date.slice(0, 7);
			(map[k] = map[k] || { total: 0 }).total += r.total;
		});
		return Object.keys(map).sort().map(function (k) {
			return { label: gran === "week" ? ("wk " + ddmm(k)) : fmtMonth(k), total: map[k].total };
		});
	}
	function renderGran() {
		$("#ofgran").innerHTML = [["day", "Day"], ["week", "Week"], ["month", "Month"]].map(function (o) {
			return '<button data-g="' + o[0] + '"' + (state.granularity === o[0] ? ' class="on"' : '') + '>' + o[1] + '</button>';
		}).join("");
		$("#ofgran").querySelectorAll("button").forEach(function (b) {
			b.onclick = function () { state.granularity = b.dataset.g; renderGran(); renderChart(DATA.daily || []); };
		});
	}
	function renderChart(daily) {
		var rows = bucketDaily(daily || [], state.granularity);
		$("#ofchart-hint").textContent = (daily && daily.length) ? (fmtDate(daily[0].date) + " → " + fmtDate(daily[daily.length - 1].date)) : "";
		mkChart("ofchart", {
			type: "bar",
			data: { labels: rows.map(function (r) { return r.label; }), datasets: [{ label: "Collected", data: rows.map(function (r) { return r.total; }), backgroundColor: "#059669", borderRadius: 3 }] },
			options: {
				responsive: true, maintainAspectRatio: false,
				plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return money(c.parsed.y); } } } },
				scales: {
					x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, font: { size: 10 } } },
					y: { ticks: { callback: function (v) { return shortMoney(v); }, font: { size: 10 } }, grid: { color: "#eef1f4" } },
				},
			},
		});
	}

	// -------------------------------------------------------------- tables
	function emptyBox() { return '<div class="empty"><div class="t">No data</div><div class="s">Nothing matches the current filters.</div></div>'; }
	function tableShell(host, headHtml) { host.innerHTML = '<table><thead>' + headHtml + '</thead><tbody></tbody></table>'; return host.querySelector("tbody"); }

	function renderSanstha(rows) {
		var host = $("#ofsanstha");
		if (!rows.length) { host.innerHTML = emptyBox(); return; }
		var tb = tableShell(host, '<tr><th>Sanstha company</th><th class="r">JEs</th><th class="r">Collected</th></tr>');
		rows.forEach(function (r) {
			var exp = state.expanded && state.expanded.kind === "sanstha" && state.expanded.key === r.company;
			var tr = document.createElement("tr"); tr.className = "drow" + (exp ? " expanded" : "");
			tr.innerHTML = "<td>" + esc(r.company) + '</td><td class="r"><span class="jepill">' + r.count +
				'</span></td><td class="r g bold">' + money(r.total) + "</td>";
			tr.onclick = function () { toggleExpand("sanstha", r.company); };
			tb.appendChild(tr);
			if (exp) tb.appendChild(expandRow("sanstha", r.company, "By college", ["College", "Collected", "JEs"]));
		});
	}
	function renderHead(rows) {
		var host = $("#ofhead");
		if (!rows.length) { host.innerHTML = emptyBox(); return; }
		var tb = tableShell(host, '<tr><th>Fee head</th><th class="r">JEs</th><th class="r">Collected</th><th></th></tr>');
		rows.forEach(function (r) {
			var tr = document.createElement("tr"); tr.className = "drow";
			tr.innerHTML = "<td>" + esc(r.fee_head || "—") + '</td><td class="r"><span class="jepill">' + r.count +
				'</span></td><td class="r bold">' + money(r.total) + '</td><td class="r"><span class="dim" style="font-size:11px">view JEs →</span></td>';
			tr.onclick = function () { openListDrawer("Fee head — " + (r.fee_head || "—"), rangeLabel(), scoped({ fee_head: r.fee_head })); };
			tb.appendChild(tr);
		});
	}
	function renderCollege(rows) {
		var host = $("#ofcollege");
		if (!rows.length) { host.innerHTML = emptyBox(); return; }
		var tb = tableShell(host, '<tr><th>College</th><th>Sanstha</th><th class="r">Live</th><th class="r">Historical</th><th class="r">Total</th><th class="r">JEs</th></tr>');
		rows.forEach(function (r) {
			var exp = state.expanded && state.expanded.kind === "college" && state.expanded.key === r.institution;
			var tr = document.createElement("tr"); tr.className = "drow" + (exp ? " expanded" : "");
			tr.innerHTML = '<td><span class="code">' + esc(r.institution) + '</span></td><td><span class="co2">' + esc(r.sanstha || "—") +
				'</span></td><td class="r">' + money(r.live) + '</td><td class="r">' + money(r.historical) +
				'</td><td class="r bold">' + money(r.total) + '</td><td class="r"><span class="jepill">' + r.count + "</span></td>";
			tr.onclick = function () { toggleExpand("college", r.institution); };
			tb.appendChild(tr);
			if (exp) tb.appendChild(expandRow("college", r.institution, "By fee head", ["Fee head", "Collected", "JEs"]));
		});
	}

	// generic expand row: mini daily chart + a breakdown minitable, async-filled
	function expandRow(kind, key, breakdownTitle, cols) {
		var span = kind === "sanstha" ? 3 : 6;
		var tr = document.createElement("tr"); tr.className = "exprow";
		var td = document.createElement("td"); td.className = "exp-cell"; td.colSpan = span;
		var cid = "expchart_" + kind;
		td.innerHTML = '<div class="exp-inner">' +
			'<div><h5>' + esc(key) + ' · daily</h5><div class="exp-chart"><canvas id="' + cid + '"></canvas></div>' +
			'<div class="exp-link"><a data-jes="1">View all JEs in scope →</a></div></div>' +
			'<div><h5>' + breakdownTitle + '</h5><table class="minitable"><thead><tr>' +
			cols.map(function (c, i) { return '<th' + (i >= 1 ? ' class="r"' : "") + ">" + c + "</th>"; }).join("") +
			'</tr></thead><tbody id="expbreak_' + kind + '"><tr><td colspan="' + cols.length + '" class="muted" style="padding:10px">Loading…</td></tr></tbody></table></div></div>';
		tr.appendChild(td);

		var f = kind === "sanstha" ? scoped({ sansthas: [key] }) : scoped({ institutions: [key] });
		call("daily", null, f).then(function (d) { drawMini(cid, d || []); });
		if (kind === "sanstha") {
			call("by_college", null, f).then(function (list) { fillBreak("expbreak_sanstha", (list || []).map(function (x) {
				return [esc(x.institution), money(x.total), x.count];
			}), 3); });
		} else {
			call("by_fee_head", null, f).then(function (list) { fillBreak("expbreak_college", (list || []).map(function (x) {
				return [esc(x.fee_head || "—"), money(x.total), x.count];
			}), 3); });
		}
		setTimeout(function () {
			var a = td.querySelector("[data-jes]");
			if (a) a.onclick = function (e) {
				e.stopPropagation();
				openListDrawer((kind === "sanstha" ? "Sanstha — " : "College — ") + key, rangeLabel(), f);
			};
		}, 0);
		return tr;
	}
	function fillBreak(id, rowsArr, ncol) {
		var body = $("#" + id); if (!body) return;
		if (!rowsArr.length) { body.innerHTML = '<tr><td colspan="' + ncol + '" class="muted" style="padding:10px">Nothing in scope.</td></tr>'; return; }
		body.innerHTML = rowsArr.map(function (cells) {
			return "<tr>" + cells.map(function (c, i) { return '<td' + (i >= 1 ? ' class="r mono"' : "") + ">" + c + "</td>"; }).join("") + "</tr>";
		}).join("");
	}
	function drawMini(cid, daily) {
		var rows = daily || [];
		mkChart(cid, {
			type: "bar",
			data: { labels: rows.map(function (d) { return ddmm(d.date); }), datasets: [{ data: rows.map(function (d) { return d.total; }), backgroundColor: "#059669", borderRadius: 2 }] },
			options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { grid: { display: false }, ticks: { font: { size: 9 }, color: "#9ca3af", maxTicksLimit: 10, maxRotation: 0 } }, y: { grid: { color: "#f0f2f5" }, ticks: { font: { size: 9 }, color: "#9ca3af", callback: function (v) { return shortMoney(v); } } } } },
		});
	}
	function toggleExpand(kind, key) {
		var same = state.expanded && state.expanded.kind === kind && state.expanded.key === key;
		state.expanded = same ? null : { kind: kind, key: key };
		// Re-render both tables so only one expand row is open globally.
		renderSanstha(DATA.sanstha || []);
		renderCollege(DATA.recon || []);
	}

	// -------------------------------------------------------------- feed
	function renderFeed(rows) {
		var host = $("#offeed");
		if (!rows || !rows.length) { host.innerHTML = '<div class="empty"><div class="t">No postings</div></div>'; return; }
		var items = rows.map(function (r) {
			var canc = r.status === "Cancelled";
			var amt = '<span class="tlamt' + (canc ? " struck" : "") + '">' + money(r.amount) + "</span>";
			var note = canc ? ('<div class="tlcancel">Cancelled' + (r.replaced_by_ref ? ' — reposted as <span class="mono">' + esc(r.replaced_by_ref) + "</span>" : "") + "</div>") : "";
			return '<div class="tlitem" data-ref="' + esc(r.ref) + '"><div class="tldot ' + (canc ? "x" : "c") + '"></div><div class="tlbody">' +
				'<div class="tlrow1"><div class="tlmeta"><b>' + esc(r.institution || "—") + "</b> " + esc(r.fee_head || "") +
				'<span class="ch">' + r.channel + " • " + r.source + "</span></div>" + amt + "</div>" +
				'<div class="tlref">' + esc(r.ref) + " → " + esc(r.company) + "</div>" +
				'<div class="tltime">' + esc(prettyDT(r.dt)) + " • " + esc(fmtDate(r.posting_date)) + "</div>" + note + "</div></div>";
		}).join("");
		host.innerHTML = '<div class="timeline">' + items + "</div>";
		host.querySelectorAll(".tlitem").forEach(function (it) {
			it.onclick = function () {
				var j = (DATA.feed || []).find(function (x) { return x.ref === it.dataset.ref; });
				if (j) openJEDrawer(j);
			};
		});
	}

	// -------------------------------------------------------------- drawers
	function openDrawer() { $("#ofscrim").classList.add("open"); $("#ofdrawer").classList.add("open"); }
	function closeDrawer() { $("#ofscrim").classList.remove("open"); $("#ofdrawer").classList.remove("open"); }
	function drawerHead(t, s) {
		return '<div class="drawer-h"><div><div class="dt">' + esc(t) + '</div><div class="ds">' + esc(s) + '</div></div>' +
			'<div class="drawer-close" id="ofdrawerClose"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="6" y1="18" x2="18" y2="6"/></svg></div></div>';
	}
	function jeEntry(j) {
		var canc = j.status === "Cancelled";
		var link = "/app/journal-entry/" + encodeURIComponent(j.name);
		return '<div class="jeentry"><div class="jedot tldot ' + (canc ? "x" : "c") + '" style="margin-top:6px"></div>' +
			'<div style="flex:1;min-width:0"><div class="jdate">' + esc(prettyDT(j.dt)) + " • " + esc(fmtDate(j.posting_date)) + "</div>" +
			'<div class="jref">' + esc(j.ref) + "</div>" +
			'<div class="jch"><b>' + esc(j.institution || "—") + "</b> · " + esc(j.fee_head || "") + " · " + cap(j.channel) + " · " + cap(j.source) +
			(canc ? ' · <span style="color:var(--cancel)">Cancelled</span>' : "") + "</div></div>" +
			'<div class="jamt"><div class="a' + (canc ? " struck" : "") + '" style="' + (canc ? "text-decoration:line-through;color:var(--tx3)" : "") + '">' + money(j.amount) + "</div>" +
			'<a href="' + link + '" target="_blank">Open in ERPNext →</a></div></div>';
	}
	function openJEDrawer(j) {
		$("#ofdrawer").innerHTML = drawerHead("Journal Entry", j.name) +
			'<div class="drawer-body">' + jeEntry(j) +
			'<div class="drawer-note"><b>' + esc(j.company) + "</b><br>Income head: <span class=\"mono\">" + esc(j.income_acct || "") +
			'</span><br>Bank/Cash ledger: <span class="mono">' + esc(j.ledger || "") + "</span><br>Source: " + cap(j.source) +
			(j.status === "Cancelled" && j.replaced_by_ref ? '<br><span style="color:var(--cancel)">Cancelled</span> — reposted as <span class="mono">' + esc(j.replaced_by_ref) + "</span>." : (j.status === "Cancelled" ? '<br><span style="color:var(--cancel)">Cancelled</span>.' : "")) +
			"</div></div>";
		wireDrawer(); openDrawer();
	}
	function openListDrawer(title, sub, flt) {
		$("#ofdrawer").innerHTML = drawerHead(title, sub) + '<div class="drawer-body"><div class="muted" style="padding:10px">Loading…</div></div>';
		openDrawer(); wireDrawer();
		call("feed", { limit: 200 }, flt).then(function (list) {
			list = list || [];
			var total = list.reduce(function (a, b) { return a + (b.amount || 0); }, 0);
			$("#ofdrawer").innerHTML = drawerHead(title, sub + " · " + list.length + " JEs · " + money(total)) +
				'<div class="drawer-body">' + (list.length ? list.map(jeEntry).join("") :
					'<div class="empty"><div class="t">No entries</div></div>') + "</div>";
			wireDrawer();
		});
	}
	function wireDrawer() {
		var c = $("#ofdrawerClose"); if (c) c.onclick = closeDrawer;
		$("#ofscrim").onclick = closeDrawer;
	}

	// -------------------------------------------------------------- exports
	function rangeLabel() { return fmtDate(state.date_from) + " → " + fmtDate(state.date_to); }
	function toCSV(rows) {
		return rows.map(function (r) {
			return r.map(function (c) {
				c = c == null ? "" : String(c);
				var needsQuote = c.indexOf('"') >= 0 || c.indexOf(",") >= 0 || c.indexOf("\n") >= 0;
				return needsQuote ? '"' + c.split('"').join('""') + '"' : c;
			}).join(",");
		}).join("\n");
	}
	function downloadCSV(name, rows) {
		var blob = new Blob([toCSV(rows)], { type: "text/csv;charset=utf-8;" });
		var url = URL.createObjectURL(blob), a = document.createElement("a");
		a.href = url; a.download = name; document.body.appendChild(a); a.click();
		document.body.removeChild(a); URL.revokeObjectURL(url);
	}
	function exportCSV(which) {
		var stamp = state.date_from + "_" + state.date_to;
		if (which === "sanstha") {
			downloadCSV("other-fees-by-sanstha-" + stamp + ".csv",
				[["Sanstha", "JEs", "Collected"]].concat((DATA.sanstha || []).map(function (r) { return [r.company, r.count, r.total]; })));
		} else if (which === "head") {
			downloadCSV("other-fees-by-head-" + stamp + ".csv",
				[["Fee head", "JEs", "Collected"]].concat((DATA.head || []).map(function (r) { return [r.fee_head, r.count, r.total]; })));
		} else if (which === "college") {
			downloadCSV("other-fees-by-college-" + stamp + ".csv",
				[["College", "Sanstha", "Live", "Historical", "Total", "JEs"]].concat((DATA.recon || []).map(function (r) { return [r.institution, r.sanstha, r.live, r.historical, r.total, r.count]; })));
		}
	}
	function wireActions() {
		ROOT.querySelectorAll(".csvbtn").forEach(function (b) { b.onclick = function () { exportCSV(b.dataset.csv); }; });
		$("#ofpdf").onclick = function () {
			window.open("/api/method/dux_cybervidya.api.other_fees_dashboard.other_fees_pdf?filters=" + encodeURIComponent(JSON.stringify(state)), "_blank");
		};
	}

	// -------------------------------------------------------------- orchestration
	function prevWindow() {
		var f = new Date(state.date_from + "T00:00:00"), t = new Date(state.date_to + "T00:00:00");
		var len = Math.round((t - f) / 86400000) + 1;
		var pt = new Date(f); pt.setDate(pt.getDate() - 1);
		var pf = new Date(pt); pf.setDate(pf.getDate() - (len - 1));
		return scoped({ date_from: pf.toISOString().slice(0, 10), date_to: pt.toISOString().slice(0, 10) });
	}
	function refresh() {
		loading(true);
		Promise.all([
			call("summary"), call("daily"), call("by_sanstha"), call("by_fee_head"),
			call("reconcile"), call("feed"),
			call("summary", null, prevWindow()),
		]).then(function (res) {
			DATA.summary = res[0]; DATA.daily = res[1]; DATA.sanstha = res[2]; DATA.head = res[3];
			DATA.recon = res[4]; DATA.feed = res[5]; DATA.prev = res[6];
			renderSummary(DATA.summary, DATA.prev);
			renderChart(DATA.daily);
			renderSanstha(DATA.sanstha);
			renderHead(DATA.head);
			renderCollege(DATA.recon);
			renderFeed(DATA.feed);
			$("#offoot").innerHTML = "Showing " + rangeLabel();
			loading(false);
		}).catch(function (e) {
			loading(false);
			frappe.msgprint({ title: "Report error", message: (e && e.message) || String(e), indicator: "red" });
		});
	}

	function init(root) {
		ROOT = root;
		root.classList.add("dux-of-dash");
		root.innerHTML = BODY;
		document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawer(); });
		renderGran();
		wireActions();
		call("options").then(function (o) {
			OPTS = o || OPTS;
			renderFilters();
			refresh();
		});
	}

	window.DuxOtherFeesDashboard = { init: init };
})();
