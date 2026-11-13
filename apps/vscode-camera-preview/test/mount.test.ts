import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Vector3 } from 'three';
import { parseConfig } from '../config.ts';
import { previewMount } from '../media/cameras.ts';
// Robot-frame axes of WPILib's Java `new Rotation3d(roll, pitch, yaw)`, in degrees.
import rotations from './fixtures/wpilib-rotations.json' with { type: 'json' };

const close = (a: number[], b: number[]) => {
	a.forEach((v, i) => {
		assert.ok(Math.abs(v - b[i]) < 1e-10, `${a.join(',')} != ${b.join(',')}`);
	});
};
const mount = (fields: string) => previewMount(parseConfig(`[cameras.camera]\nmount = { ${fields} }`)[0]);

void test('spot.toml roll, pitch and yaw rotate the camera like WPILib Rotation3d', () => {
	for (const { rollPitchYawDeg, worldAxes } of rotations) {
		const [roll, pitch, yaw] = rollPitchYawDeg;
		const { quaternion } = mount(`roll = ${roll}, pitch = ${pitch}, yaw = ${yaw}`);
		for (const [i, axis] of [
			[1, 0, 0],
			[0, 1, 0],
			[0, 0, 1],
		].entries()) {
			close(new Vector3(...axis).applyQuaternion(quaternion).toArray(), worldAxes[i]);
		}
	}
});

void test('positive pitch points the lens down and positive yaw points it left', () => {
	assert.ok(new Vector3(1, 0, 0).applyQuaternion(mount('pitch = 15').quaternion).z < 0);
	assert.ok(new Vector3(1, 0, 0).applyQuaternion(mount('pitch = -15').quaternion).z > 0);
	close(new Vector3(1, 0, 0).applyQuaternion(mount('yaw = 90').quaternion).toArray(), [0, 1, 0]);
});

void test('mount translation is in meters, X forward, Y left, Z up', () => {
	assert.deepEqual(mount('x = 0.3, y = -0.1, z = 0.25').position.toArray(), [0.3, -0.1, 0.25]);
});
