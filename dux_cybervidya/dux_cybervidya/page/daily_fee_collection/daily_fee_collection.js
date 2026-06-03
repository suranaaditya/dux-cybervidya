frappe.pages['daily-fee-collection'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Daily Fee Collection',
		single_column: true,
	});

	frappe.require([
		'/assets/dux_cybervidya/css/daily_fee_collection.css',
		'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js',
		'/assets/dux_cybervidya/js/daily_fee_collection.js',
	], () => {
		window.DuxCyberVidyaDashboard.init(page.body[0]);
	});
};
