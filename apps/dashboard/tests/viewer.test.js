import { test } from 'vite-plus/test';
import assert from 'node:assert/strict';
import { rotate, angles, quaternion, cameraAngles, cameraQuaternion, robotPose } from '@spot/camera-viewer';
const close = (a, b) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < 1e-10, `${a} != ${b}`));

test('WPILib camera Pitch lowers the lens at every yaw; negative Pitch raises it', () => {
	for (const yaw of [-180, -45, 0, 90, 179]) {
		for (const roll of [-40, 0, 30]) {
			const down = rotate(cameraQuaternion(yaw, 20, roll), [1, 0, 0]);
			const up = rotate(cameraQuaternion(yaw, -20, roll), [1, 0, 0]);
			assert.ok(up[2] > 0);
			assert.ok(down[2] < 0);
			close(up, [
				Math.cos((yaw * Math.PI) / 180) * Math.cos(Math.PI / 9),
				Math.sin((yaw * Math.PI) / 180) * Math.cos(Math.PI / 9),
				Math.sin(Math.PI / 9),
			]);
		}
	}
});

test('robot geometry readback and reset round-trip through native WPILib controls', () => {
	for (const values of [
		[0, 0, 0],
		[30, 25, -15],
		[-90, -35, 40],
	]) {
		const stored = quaternion(...values);
		close(cameraAngles(stored), values);
		const restored = cameraQuaternion(...cameraAngles(stored));
		for (const axis of [
			[1, 0, 0],
			[0, 1, 0],
			[0, 0, 1],
		])
			close(rotate(restored, axis), rotate(stored, axis));
	}
});

test('WPILib pitch and robot mount transforms retain their native convention', () => {
	const q = quaternion(0, 20, 0);
	assert.ok(rotate(q, [1, 0, 0])[2] < 0);
	close(angles(q), [0, 20, 0]);
	const mount = { translation: [0.3, 0.1, 0.5], quaternion: q };
	const pose = robotPose(mount, mount);
	close(pose.translation, [0, 0, 0]);
	close(pose.quaternion, [1, 0, 0, 0]);
});
