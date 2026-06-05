/* Other Fees / Sanstha Collection — dashboard front-end.
   Renders the read-only report served by
   dux_cybervidya.api.other_fees_dashboard.  Namespaced under .dux-of-dash. */
(function () {
	"use strict";

	var ROOT = null, CHART = null;
	var OPTS = { sansthas: [], institutions: [] };
	var state = {
		date_from: "2026-04-01",
		date_to: frappe.datetime.get_today(),
		channel: "all",   // all | bank | cash
		source: "all",    // all | live | historical
		status: "active", // active | cancelled | both
		sansthas: [],
		institutions: [],
		q: "",
	};

	var INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
	function money(n) { return "₹" + INR.format(n || 0); }
	function el(html) { var d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstChild; }
	function esc(s) { return frappe.utils.escape_html(s == null ? "" : String(s)); }

	function call(method, extra) {
		var args = Object.assign({ filters: JSON.stringify(state) }, extra || {});
		return frappe.call({
			method: "dux_cybervidya.api.other_fees_dashboard." + method,
			args: args,
		}).then(function (r) { return r.message; });
	}

	// -------------------------------------------------------------- skeleton
	var BODY = '' +
		'<div class="topbar">' +
		'  <div class="brand"><div class="logo">OF</div>' +
		'    <div><div class="ttl">Other Fees / Sanstha Collection</div>' +
		'    <div class="sub">CyberVidya head-wise fees → sanstha income</div></div></div>' +
		'  <div class="spacer"></div><div class="statpills" id="ofpills"></div>' +
		'</div>' +
		'<div class="filterbar" id="offilters"></div>' +
		'<div class="page">' +
		'  <div class="summary cvfade" id="ofsummary"></div>' +
		'  <div class="card"><div class="card-h"><h3>Daily collections</h3>' +
		'     <span class="hint" id="ofchart-hint"></span></div>' +
		'     <div class="chartwrap"><canvas id="ofchart"></canvas></div></div>' +
		'  <div class="card"><div class="card-h"><h3>By sanstha</h3></div>' +
		'     <div class="cvfade" id="ofsanstha"></div></div>' +
		'  <div class="card"><div class="card-h"><h3>By fee head</h3>' +
		'     <span class="hint">across all sansthas in scope</span></div>' +
		'     <div class="cvfade" id="ofhead"></div></div>' +
		'  <div class="card"><div class="card-h"><h3>By college — reconciliation</h3>' +
		'     <span class="hint">live vs historical, recovered from the JE reference</span></div>' +
		'     <div class="cvfade" id="ofcollege"></div></div>' +
		'  <div class="card"><div class="card-h"><h3>Recent activity</h3>' +
		'     <span class="hint">most recent postings</span></div>' +
		'     <div class="cvfade" id="offeed"></div></div>' +
		'  <div class="foot"><div class="p">Dux CyberVidya • other-fees report</div>' +
		'     <div class="p" id="offoot"></div></div>' +
		'</div>';

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
		// items: [{val, text}]
		var chips = items.map(function (it) {
			var on = state[key].indexOf(it.val) >= 0;
			return '<button class="seg-chip' + (on ? ' on" ' : '" ') +
				'data-chipkey="' + key + '" data-chipval="' + esc(it.val) + '">' + esc(it.text) + '</button>';
		}).join("");
		if (!items.length) return "";
		return '<div class="fgroup"><span class="flabel">' + label + '</span>' +
			'<div class="seg" style="flex-wrap:wrap;max-width:560px">' + chips + '</div></div>';
	}

	function renderFilters() {
		var bar = ROOT.querySelector("#offilters");
		var instItems = OPTS.institutions.map(function (i) { return { val: i.code, text: i.code }; });
		var sanItems = OPTS.sansthas.map(function (s) { return { val: s.company, text: s.abbr || s.company }; });
		bar.innerHTML =
			'<div class="fgroup"><span class="flabel">From</span>' +
			'  <input type="date" id="offrom" value="' + state.date_from + '"></div>' +
			'<div class="fgroup"><span class="flabel">To</span>' +
			'  <input type="date" id="ofto" value="' + state.date_to + '"></div>' +
			seg("Channel", "channel", [["all", "All"], ["bank", "Bank"], ["cash", "Cash"]]) +
			seg("Source", "source", [["all", "All"], ["live", "Live"], ["historical", "Historical"]]) +
			seg("Status", "status", [["active", "Active"], ["cancelled", "Cancelled"], ["both", "Both"]]) +
			chipRow("Sanstha", "sansthas", sanItems) +
			chipRow("College", "institutions", instItems) +
			'<div class="fgroup"><input type="text" id="ofq" placeholder="ref contains…" ' +
			'   value="' + esc(state.q) + '" style="height:30px;border:1px solid var(--bd);border-radius:7px;padding:0 9px;font-size:12px"></div>' +
			'<span class="clearall show" id="ofclear">Reset</span>';

		// date inputs
		bar.querySelector("#offrom").onchange = function (e) { state.date_from = e.target.value; refresh(); };
		bar.querySelector("#ofto").onchange = function (e) { state.date_to = e.target.value; refresh(); };
		bar.querySelector("#ofq").onkeydown = function (e) {
			if (e.key === "Enter") { state.q = e.target.value.trim(); refresh(); }
		};
		// segs
		bar.querySelectorAll(".seg button[data-k]").forEach(function (b) {
			b.onclick = function () { state[b.dataset.k] = b.dataset.v; renderFilters(); refresh(); };
		});
		// chips (multi-select toggle)
		bar.querySelectorAll(".seg-chip").forEach(function (b) {
			b.onclick = function () {
				var k = b.dataset.chipkey, v = b.dataset.chipval, arr = state[k];
				var i = arr.indexOf(v);
				if (i >= 0) arr.splice(i, 1); else arr.push(v);
				renderFilters(); refresh();
			};
		});
		bar.querySelector("#ofclear").onclick = function () {
			state.channel = state.source = "all"; state.status = "active";
			state.sansthas = []; state.institutions = []; state.q = "";
			renderFilters(); refresh();
		};
	}

	// -------------------------------------------------------------- renders
	function loading(on) {
		ROOT.querySelectorAll(".cvfade").forEach(function (e) { e.classList.toggle("loading", !!on); });
	}

	function sumcard(cls, k, v, m) {
		return '<div class="sumcard ' + cls + '"><div class="k">' + k + '</div>' +
			'<div class="v">' + v + '</div><div class="m">' + (m || "") + '</div></div>';
	}

	function renderSummary(s) {
		ROOT.querySelector("#ofsummary").innerHTML =
			sumcard("c", "Total collected", money(s.total), s.count + " JEs • " + s.sansthas + " sansthas • " + s.colleges + " colleges") +
			sumcard("n", "Bank", money(s.bank.total), s.bank.count + " JEs") +
			sumcard("r", "Cash", money(s.cash.total), s.cash.count + " JEs") +
			sumcard("x", "Cancelled", money(s.cancelled.total), s.cancelled.count + " JEs (in scope)");
		var pills = ROOT.querySelector("#ofpills");
		pills.innerHTML = '<span class="statpill amber"><span class="dot"></span>' +
			'Live ' + money(s.live.total) + ' • Historical ' + money(s.historical.total) + '</span>';
	}

	function renderChart(rows) {
		var hint = ROOT.querySelector("#ofchart-hint");
		hint.textContent = rows.length ? (rows[0].date + " → " + rows[rows.length - 1].date) : "";
		var ctx = ROOT.querySelector("#ofchart").getContext("2d");
		var labels = rows.map(function (r) { return r.date.slice(5); });
		var data = rows.map(function (r) { return r.total; });
		if (CHART) CHART.destroy();
		CHART = new Chart(ctx, {
			type: "bar",
			data: { labels: labels, datasets: [{ label: "Collected", data: data, backgroundColor: "#059669", borderRadius: 3 }] },
			options: {
				responsive: true, maintainAspectRatio: false,
				plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return money(c.parsed.y); } } } },
				scales: {
					x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, font: { size: 10 } } },
					y: { ticks: { callback: function (v) { return INR.format(v); }, font: { size: 10 } }, grid: { color: "#eef1f4" } },
				},
			},
		});
	}

	function table(headCols, bodyRows) {
		if (!bodyRows.length) return '<div class="empty"><div class="t">No data</div><div class="s">Nothing matches the current filters.</div></div>';
		var thead = "<tr>" + headCols.map(function (c) {
			return '<th' + (c.r ? ' class="r"' : '') + '>' + c.t + "</th>";
		}).join("") + "</tr>";
		return '<table><thead>' + thead + '</thead><tbody>' + bodyRows.join("") + '</tbody></table>';
	}

	function renderSanstha(rows) {
		var body = rows.map(function (r) {
			return "<tr><td>" + esc(r.company) + '</td><td class="r"><span class="jepill">' + r.count +
				'</span></td><td class="r g bold">' + money(r.total) + "</td></tr>";
		});
		ROOT.querySelector("#ofsanstha").innerHTML = table(
			[{ t: "Sanstha company" }, { t: "JEs", r: 1 }, { t: "Collected", r: 1 }], body);
	}

	function renderHead(rows) {
		var body = rows.map(function (r) {
			return "<tr><td>" + esc(r.fee_head) + '</td><td class="r"><span class="jepill">' + r.count +
				'</span></td><td class="r bold">' + money(r.total) + "</td></tr>";
		});
		ROOT.querySelector("#ofhead").innerHTML = table(
			[{ t: "Fee head" }, { t: "JEs", r: 1 }, { t: "Collected", r: 1 }], body);
	}

	function renderCollege(rows) {
		var body = rows.map(function (r) {
			return "<tr><td><span class=\"code\">" + esc(r.institution) + "</span></td><td>" +
				'<span class="co2">' + esc(r.sanstha || "—") + "</span></td>" +
				'<td class="r">' + money(r.live) + '</td><td class="r">' + money(r.historical) +
				'</td><td class="r bold">' + money(r.total) + '</td><td class="r"><span class="jepill">' + r.count + "</span></td></tr>";
		});
		ROOT.querySelector("#ofcollege").innerHTML = table(
			[{ t: "College" }, { t: "Sanstha" }, { t: "Live", r: 1 }, { t: "Historical", r: 1 },
			 { t: "Total", r: 1 }, { t: "JEs", r: 1 }], body);
	}

	function renderFeed(rows) {
		if (!rows.length) {
			ROOT.querySelector("#offeed").innerHTML = '<div class="empty"><div class="t">No postings</div></div>';
			return;
		}
		var items = rows.map(function (r) {
			var dotc = r.status === "Cancelled" ? "x" : "c";
			var amt = '<span class="tlamt' + (r.status === "Cancelled" ? " struck" : "") + '">' + money(r.amount) + "</span>";
			return '<div class="tlitem"><div class="tldot ' + dotc + '"></div><div class="tlbody">' +
				'<div class="tlrow1"><div class="tlmeta"><b>' + esc(r.institution || "—") + "</b> " +
				esc(r.fee_head || "") + '<span class="ch">' + r.channel + " • " + r.source + "</span></div>" + amt + "</div>" +
				'<div class="tlref">' + esc(r.ref) + " → " + esc(r.company) + "</div>" +
				'<div class="tltime">' + esc((r.dt || "").replace("T", " ").slice(0, 19)) + " • " + esc(r.posting_date) + "</div>" +
				"</div></div>";
		}).join("");
		ROOT.querySelector("#offeed").innerHTML = '<div class="timeline">' + items + "</div>";
	}

	// -------------------------------------------------------------- orchestration
	function refresh() {
		loading(true);
		Promise.all([
			call("summary"), call("daily"), call("by_sanstha"),
			call("by_fee_head"), call("by_college"), call("reconcile"), call("feed"),
		]).then(function (res) {
			var summary = res[0], daily = res[1], sanstha = res[2],
				head = res[3], college = res[4], recon = res[5], feed = res[6];
			renderSummary(summary);
			renderChart(daily);
			renderSanstha(sanstha);
			renderHead(head);
			renderCollege(recon);   // reconcile carries live/historical split
			renderFeed(feed);
			ROOT.querySelector("#offoot").innerHTML = "Showing " + state.date_from + " → " + state.date_to;
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
		call("options").then(function (o) {
			OPTS = o || OPTS;
			renderFilters();
			refresh();
		});
	}

	window.DuxOtherFeesDashboard = { init: init };
})();
