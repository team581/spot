const test = require('node:test');
const assert = require('node:assert/strict');
const { rotate } = require('@spot/camera-viewer');
const { parseConfig } = require('../config.ts');
const { previewMount } = require('../media/cameras.ts');
// Robot-frame axes of WPILib's Java `new Rotation3d(roll, pitch, yaw)`, in degrees.
const rotations = require('./fixtures/wpilib-rotations.json');
const close = (a, b) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < 1e-10, `${a} != ${b}`));
const mount = (fields) => previewMount(parseConfig(`[cameras.camera]\nmount = { ${fields} }`)[0]);

void test('spot.toml roll, pitch and yaw rotate the camera like WPILib Rotation3d', () => {
	for (const { rollPitchYawDeg, worldAxes } of rotations) {
		const [roll, pitch, yaw] = rollPitchYawDeg;
		const { quaternion } = mount(`roll = ${roll}, pitch = ${pitch}, yaw = ${yaw}`);
		for (const [i, axis] of [
			[1, 0, 0],
			[0, 1, 0],
			[0, 0, 1],
		].entries())
			close(rotate(quaternion, axis), worldAxes[i]);
	}
});

void test('positive pitch points the lens down and positive yaw points it left', () => {
	assert.ok(rotate(mount('pitch = 15').quaternion, [1, 0, 0])[2] < 0);
	assert.ok(rotate(mount('pitch = -15').quaternion, [1, 0, 0])[2] > 0);
	close(rotate(mount('yaw = 90').quaternion, [1, 0, 0]), [0, 1, 0]);
});

void test('mount translation is in meters, X forward, Y left, Z up', () => {
	assert.deepEqual(mount('x = 0.3, y = -0.1, z = 0.25').translation, [0.3, -0.1, 0.25]);
});
