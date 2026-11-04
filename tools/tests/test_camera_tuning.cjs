// Run with node --test tools/tests/test_camera_tuning.cjs.
const { test } = require('node:test'),
	assert = require('node:assert/strict'),
	fs = require('node:fs'),
	vm = require('node:vm');
const html = fs.readFileSync(require.resolve('../alpha_dashboard.html'), 'utf8');
const source = html.slice(html.indexOf('// Camera tuning'), html.indexOf('const preferences='));
function setup(fetch) {
	const elements = {};
	const $ = (id) =>
		(elements[id] ??= { innerHTML: '', textContent: '', className: '', disabled: false, hidden: false });
	const sandbox = {
		$,
		selected: '1',
		disconnected: false,
		frozen: false,
		fetch,
		AbortSignal,
		document: { querySelectorAll: () => [] },
		escapeHtml: (v) =>
			String(v).replace(
				/[&<>"']/g,
				(c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
			),
	};
	vm.createContext(sandbox);
	vm.runInContext(source, sandbox);
	return { sandbox, elements };
}
const exposure = {
	name: 'exposure_time_absolute',
	label: 'Exposure',
	type: 'int',
	min: 50,
	max: 10000,
	step: 1,
	value: 50,
	default: 166,
	factor: 100,
	unit: 'µs',
	description: 'Motion blur',
	writable: true,
	flags: '',
};
test('exposure inputs and defaults are rendered in microseconds using device bounds', () => {
	const { sandbox } = setup();
	const markup = sandbox.controlMarkup(exposure);
	assert.match(markup, /min="5000"/);
	assert.match(markup, /max="1000000"/);
	assert.match(markup, /step="100"/);
	assert.match(markup, /value="5000"/);
	assert.match(markup, /Default: 16600/);
	assert.match(sandbox.controlMarkup({ ...exposure, writable: false, flags: 'inactive' }), /disabled/);
});
test('manual input sends raw UVC units and the selected camera token', async () => {
	let sent;
	const { sandbox, elements } = setup(async (url, options) => {
		sent = JSON.parse(options.body);
		assert.equal(options.headers['X-Camera-Token'], 'token');
		return { ok: true, json: async () => ({ camera_id: '1', token: 'token', controls: [exposure] }) };
	});
	sandbox.renderControls({ camera_id: '1', token: 'token', controls: [exposure] });
	elements['#control-exposure_time_absolute'] = { value: '6000', reportValidity: () => true };
	await sandbox.applyControl('exposure_time_absolute');
	assert.deepEqual(sent, { camera_id: '1', name: 'exposure_time_absolute', value: 60 });
	assert.match(elements['#control-status'].textContent, /verified/);
});
test('late camera response cannot overwrite the newly selected camera', async () => {
	const pending = [];
	const { sandbox, elements } = setup(() => new Promise((resolve) => pending.push(resolve)));
	const first = sandbox.loadControls();
	sandbox.selected = '2';
	const second = sandbox.loadControls();
	pending[1]({
		ok: true,
		json: async () => ({ camera_id: '2', token: 'second', controls: [{ ...exposure, min: 1 }] }),
	});
	await second;
	pending[0]({ ok: true, json: async () => ({ camera_id: '1', token: 'first', controls: [exposure] }) });
	await first;
	assert.equal(elements['#tuning-camera'].textContent, ' / Camera 2');
	assert.match(elements['#primary-controls'].innerHTML, /min="100"/);
	assert.doesNotMatch(elements['#primary-controls'].innerHTML, /min="5000"/);
});
test('frozen and disconnected inspection prevent writes', async () => {
	const { sandbox, elements } = setup(() => {
		throw Error('Unexpected write');
	});
	sandbox.renderControls({ camera_id: '1', token: 'token', controls: [exposure] });
	sandbox.frozen = true;
	sandbox.tuningAvailability();
	assert.equal(elements['#control-fields'].disabled, true);
	await sandbox.applyControl('exposure_time_absolute');
	sandbox.frozen = false;
	sandbox.disconnected = true;
	await sandbox.applyControl('exposure_time_absolute');
});
test('control descriptions and menu labels escape device text', () => {
	const { sandbox } = setup();
	const markup = sandbox.controlMarkup({
		...exposure,
		type: 'menu',
		label: '<bad>',
		description: '<script>',
		options: [{ value: 1, label: '<img>' }],
	});
	assert.doesNotMatch(markup, /<bad>|<script>|<img>/);
	assert.match(markup, /&lt;img&gt;/);
});
