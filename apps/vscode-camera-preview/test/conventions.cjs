const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const withCanvasEnvironment = require('./helpers/canvas.cjs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const fixtures = JSON.parse(
	fs.readFileSync(path.join(root, 'apps/robot-tester/src/test/resources/spot-camera-conventions.json')),
);
const math = require('@spot/camera-viewer');
const close = (a, b) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < 1e-10, `${a} != ${b}`));
const { geometryValues, previewGeometry } = require('../../dashboard/src/state/geometry.ts');
function renderer(provider) {
	const paths = [];
	const context = {
		strokeStyle: '',
		beginPath() {
			this.points = [];
		},
		moveTo(x, y) {
			this.points.push([x, y]);
		},
		lineTo(x, y) {
			this.points.push([x, y]);
		},
		stroke() {
			paths.push({ color: this.strokeStyle, points: this.points });
		},
		closePath() {},
		clearRect() {},
		fillText() {},
	};
	const canvas = {
		width: 1000,
		height: 720,
		getContext: () => context,
		addEventListener() {},
		removeEventListener() {},
	};
	withCanvasEnvironment(() => {
		const viewer = new math.SpotViewer(canvas, provider);
		viewer.draw();
		viewer.destroy();
	});
	return paths;
}
for (const fixture of fixtures)
	void test(`Jetson vs preview: XYZ ${fixture.exported.translation}; Java RPY ${fixture.javaRollPitchYawDeg}`, () => {
		const mount = fixture.exported;
		const readback = previewGeometry(geometryValues(mount));
		close(readback.translation, mount.translation);
		const [roll, pitch, yaw] = fixture.javaRollPitchYawDeg;
		close(math.rotate(math.quaternion(yaw, pitch, roll), [1, 0, 0]), fixture.worldAxes[0]);
		// Feed signed values into the same form state used by Jetson inspection edits.
		const edited = previewGeometry([...mount.translation, ...fixture.jetsonYawPitchRollDeg]);
		for (const [i, axis] of [
			[1, 0, 0],
			[0, 1, 0],
			[0, 0, 1],
		].entries()) {
			close(math.rotate(mount.quaternion, axis), fixture.worldAxes[i]);
			close(math.rotate(readback.quaternion, axis), fixture.worldAxes[i]);
			close(math.rotate(edited.quaternion, axis), fixture.worldAxes[i]);
		}
		const previewPaths = renderer(() => ({ inspection: true, mounts: [mount], selectedName: mount.name }));
		const jetsonPaths = renderer(() => ({ inspection: true, geometry: edited }));
		// Compare actual camera body/lens paths within subpixel floating-point tolerance.
		const a = previewPaths.filter((p) => p.color === '--blue'),
			b = jetsonPaths.filter((p) => p.color === '--blue');
		assert.equal(a.length, b.length);
		a.forEach((segment, i) => {
			assert.equal(segment.points.length, b[i].points.length);
			segment.points.forEach((point, j) => close(point, b[i].points[j]));
		});
	});
void test('the same signed pitch points in the same direction in Java and Jetson controls', () => {
	for (const pitch of [-45, -20, 0, 20, 45]) {
		const java = math.rotate(math.quaternion(0, pitch, 0), [1, 0, 0]);
		const jetson = math.rotate(math.cameraQuaternion(0, pitch, 0), [1, 0, 0]);
		close(java, jetson);
		assert.ok(pitch === 0 || Math.sign(jetson[2]) === -Math.sign(pitch));
	}
});
void test('30 inch drivebase footprint converts to metres and toggle/dimensions affect only its outline', () => {
	const mount = fixtures[0].exported;
	const render = (drivebase) =>
		renderer(() => ({ inspection: true, mounts: [mount], selectedName: mount.name, drivebase }));
	const off = render({ visible: false, length: 0.762, width: 0.762 });
	const on = render({ visible: true, length: 30 * 0.0254, width: 30 * 0.0254 });
	const wide = render({ visible: true, length: 40 * 0.0254, width: 20 * 0.0254 });
	const footprint = (paths) => paths.filter((p) => p.color === '--accent-text' && p.points.length === 4);
	assert.equal(footprint(off).length, 0);
	assert.equal(footprint(on).length, 1);
	assert.notEqual(JSON.stringify(footprint(on)), JSON.stringify(footprint(wide)));
	assert.equal(
		JSON.stringify(on.filter((p) => p.color === '--blue')),
		JSON.stringify(off.filter((p) => p.color === '--blue')),
	);
	assert.equal(footprint(render({ visible: true, length: NaN, width: 0.762 })).length, 0);
});
