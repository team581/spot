import { expect, test } from 'vite-plus/test';
import { Vector3 } from 'three';
import type { Object3D } from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { buildScene } from '../src/index';
import type { FieldCamera, Pose } from '../src/index';
// Robot-frame axes of WPILib's Java `new Rotation3d(roll, pitch, yaw)`, in degrees.
import rotations from './fixtures/wpilib-rotations.json';

/** The object a label with this text is attached to. */
function labelled(root: Object3D, text: string): Object3D {
	const found: Object3D[] = [];
	root.traverse((object) => {
		if (object instanceof CSS2DObject && object.element.textContent === text && object.parent) {
			found.push(object.parent);
		}
	});
	expect(found).toHaveLength(1);
	return found[0];
}
const mounted = (pose: Pose) =>
	labelled(buildScene({ kind: 'robot', mounts: [{ name: 'camera', pose }] }).root, 'camera');
const expectClose = (actual: Vector3, expected: number[]) => {
	for (const [i, value] of actual.toArray().entries()) {
		expect(value).toBeCloseTo(expected[i], 10);
	}
};

test('roll, pitch and yaw rotate a mount like WPILib Rotation3d', () => {
	expect.assertions(rotations.length * 10);
	for (const { rollPitchYawDeg, worldAxes } of rotations) {
		const [roll, pitch, yaw] = rollPitchYawDeg;
		const { quaternion } = mounted({ roll, pitch, yaw });
		for (const [i, axis] of [
			[1, 0, 0],
			[0, 1, 0],
			[0, 0, 1],
		].entries()) {
			expectClose(new Vector3(...axis).applyQuaternion(quaternion), worldAxes[i]);
		}
	}
});

const lens = (pose: Pose) => new Vector3(1, 0, 0).applyQuaternion(mounted(pose).quaternion);

test('positive pitch points the lens down and positive yaw points it left', () => {
	expect(lens({ pitch: 15 }).z).toBeLessThan(0);
	expect(lens({ pitch: -15 }).z).toBeGreaterThan(0);
	expectClose(lens({ yaw: 90 }), [0, 1, 0]);
});

test('mount translation is in meters, X forward, Y left, Z up', () => {
	expect(mounted({ x: 0.3, y: -0.1, z: 0.25 }).position.toArray()).toStrictEqual([0.3, -0.1, 0.25]);
});

test('a camera sits on its robot estimate like WPILib Pose3d.transformBy', () => {
	const camera: FieldCamera = {
		color: 'red',
		name: 'front',
		pose: { x: 0.3, z: 0.5 },
		robot: { x: 3, y: 2, yaw: 90 },
		tags: [],
	};
	const field = { length: 16.5, tags: [], width: 8.1 };
	const body = labelled(buildScene({ cameras: [camera], field, kind: 'field' }).root, 'front');
	const [x, y, z] = body.getWorldPosition(new Vector3()).toArray();
	expect(x).toBeCloseTo(3, 10);
	expect(y).toBeCloseTo(2.3, 10);
	expect(z).toBeCloseTo(0.5, 10);
});
