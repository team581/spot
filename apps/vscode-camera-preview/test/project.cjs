const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { discover } = require('../project.ts');
void test('discovers standalone and subproject wrappers with spaces', () => {
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
void test('shared renderer handles several cameras, hidden cameras and empty scenes', () => {
	const { buildScene } = require('@spot/camera-viewer');
	const withDocument = require('./helpers/document.cjs');
	const labels = (mounts) => {
		const texts = [];
		withDocument(() => buildScene({ inspection: true, mounts, selectedName: 'front' })).root.traverse(
			(object) => object.element && texts.push(object.element.textContent),
		);
		return texts;
	};
	const mounts = ['front', 'left'].map((name) => ({ name, translation: [0.2, 0.1, 0.3], quaternion: [1, 0, 0, 0] }));
	assert.ok(labels(mounts).includes('front'));
	assert.ok(labels(mounts).includes('left'));
	assert.ok(!labels([]).includes('front'));
});
