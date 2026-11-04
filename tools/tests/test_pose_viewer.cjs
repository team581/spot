// Run with node --test tools/tests/test_pose_viewer.cjs (no browser dependencies).
const { test } = require('node:test'),
	assert = require('node:assert/strict'),
	fs = require('node:fs'),
	vm = require('node:vm');
const html = fs.readFileSync(require.resolve('../alpha_dashboard.html'), 'utf8');
const source = html.slice(html.indexOf('function poseAngles('), html.indexOf('function inspect()'));
function setup() {
	const ctx = new Proxy({}, { get: () => () => {} }),
		elements = {};
	const $ = (id) =>
		(elements[id] ??=
			id === '#map'
				? { width: 900, height: 620, getContext: () => ctx, addEventListener() {} }
				: { checked: true, innerHTML: '' });
	const sandbox = {
		$,
		state: {
			field_available: true,
			field_tags: [{ id: 18, translation: [4.626, 3.431, 1.124], quaternion: [1, 0, 0, 0] }],
		},
		views: new Map(),
		selected: null,
		frozen: false,
		held: null,
		disconnected: false,
	};
	vm.createContext(sandbox);
	vm.runInContext(source, sandbox);
	return { sandbox, elements };
}
test('WPILib quaternion preserves up and rotates forward counterclockwise', () => {
	const { sandbox } = setup();
	const v = sandbox.rotateVector([Math.SQRT1_2, 0, 0, Math.SQRT1_2], [1, 0, 0]);
	assert.ok(Math.abs(v[0]) < 1e-12);
	assert.ok(Math.abs(v[1] - 1) < 1e-12);
	assert.equal(v[2], 0);
});
test('positive WPILib pitch points forward down and reports pitch, not roll', () => {
	const { sandbox } = setup(),
		p = Math.PI / 9,
		q = [Math.cos(p / 2), 0, Math.sin(p / 2), 0];
	const forward = sandbox.rotateVector(q, [1, 0, 0]),
		up = sandbox.rotateVector(q, [0, 0, 1]);
	assert.ok(forward[2] < 0);
	assert.ok(up[2] > 0);
	const angles = sandbox.poseAngles(q);
	assert.ok(Math.abs(angles[0]) < 1e-12);
	assert.ok(Math.abs(angles[1] - 20) < 1e-12);
	assert.ok(Math.abs(angles[2]) < 1e-12);
});
test('camera coordinates use lowest-error camera candidate and stale data clears', () => {
	const { sandbox, elements } = setup();
	const first = { translation: [7, 4, 0.6], quaternion: [0, 0, 0, 1], error_px: 0.3 };
	const t = {
		pose: { translation: [99, 99, 99] },
		tags: [{ id: 18 }],
		candidates: [{ ...first, error_px: 2, translation: [8, 4, 0.6] }, first],
	};
	assert.equal(sandbox.cameraPose(t), first);
	sandbox.map(t, true);
	assert.match(elements['#pose-coordinates'].innerHTML, /7\.000/);
	assert.match(elements['#pose-coordinates'].innerHTML, /180\.0/);
	assert.match(elements['#pose-coordinates'].innerHTML, /Tag #18/);
	assert.match(elements['#pose-coordinates'].innerHTML, /Selected camera/);
	assert.match(elements['#pose-coordinates'].innerHTML, /Alternate 1/);
	assert.match(elements['#pose-coordinates'].innerHTML, /0\.300|2\.000/);
	elements['#candidates'].checked = false;
	sandbox.map(t, true);
	assert.doesNotMatch(elements['#pose-coordinates'].innerHTML, /Alternate 1|8\.000/);
	sandbox.map(t, false);
	assert.doesNotMatch(elements['#pose-coordinates'].innerHTML, /7\.000|Tag #18/);
	sandbox.map({}, true);
	assert.match(elements['#pose-coordinates'].innerHTML, /—/);
});
