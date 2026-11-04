const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { discover } = require('../project.cjs');
test('discovers standalone and subproject wrappers with spaces', () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), 'spot preview '));
	try {
		fs.writeFileSync(path.join(root, 'gradlew'), '');
		fs.writeFileSync(path.join(root, 'build.gradle'), '');
		assert.equal(discover(path.join(root, 'src/VisionConfig.java')).task, 'exportSpotCameraPreview');
		const sub = path.join(root, 'offseason-bot');
		fs.mkdirSync(sub);
		fs.writeFileSync(path.join(sub, 'build.gradle'), '');
		const result = discover(path.join(sub, 'src/main/java/VisionConfig.java'));
		assert.equal(result.task, ':offseason-bot:exportSpotCameraPreview');
		assert.equal(result.root, root);
	} finally {
		fs.rmSync(root, { recursive: true });
	}
});
test('shared renderer handles several cameras, hidden cameras and empty scenes', () => {
	const vm = require('node:vm');
	let labels = [];
	const context = new Proxy(
		{},
		{ get: (o, k) => (k === 'fillText' ? (text) => labels.push(text) : () => {}), set: () => true },
	);
	const canvas = {
		width: 1000,
		height: 720,
		getContext: () => context,
		addEventListener() {},
		removeEventListener() {},
	};
	const sandbox = {
		ResizeObserver: class {
			observe() {}
			disconnect() {}
		},
		getComputedStyle: () => ({ getPropertyValue: () => '#888' }),
		document: { documentElement: {} },
	};
	vm.runInNewContext(fs.readFileSync(require.resolve('@spot/camera-viewer'), 'utf8'), sandbox);
	let mounts = ['front', 'left'].map((name) => ({ name, translation: [0.2, 0.1, 0.3], quaternion: [1, 0, 0, 0] }));
	const viewer = new sandbox.SpotViewer(canvas, () => ({ inspection: true, mounts, selectedName: 'front' }));
	viewer.draw();
	assert.ok(labels.includes('front'));
	assert.ok(labels.includes('left'));
	labels = [];
	mounts = [];
	viewer.draw();
	assert.ok(!labels.includes('front'));
	viewer.destroy();
});
