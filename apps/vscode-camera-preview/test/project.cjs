const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { discover } = require('../project.ts');
void test('finds the robot project spot-config.json from VisionConfig.java', () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), 'spot preview '));
	try {
		const project = path.join(root, 'offseason-bot');
		fs.mkdirSync(project);
		fs.writeFileSync(path.join(project, 'build.gradle'), '');
		const config = path.join(project, 'src/main/deploy/spot-config.json');
		assert.equal(discover(path.join(project, 'src/main/java/frc/robot/vision/VisionConfig.java')), config);
		assert.equal(discover(config), config);
		assert.throws(() => discover(path.join(os.tmpdir(), 'VisionConfig.java')), /No Gradle project/);
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
