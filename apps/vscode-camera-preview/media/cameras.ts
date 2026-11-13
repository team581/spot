import { Euler, MathUtils, Quaternion, Vector3 } from 'three';
import type { Mount } from '@spot/camera-viewer';
import type { PreviewCamera } from '../config';

/** A camera's mount in the viewer's form; angles follow WPILib Rotation3d(roll, pitch, yaw). */
export function previewMount({ name, mount: { x, y, z, roll, pitch, yaw } }: PreviewCamera): Mount {
	return {
		name,
		position: new Vector3(x, y, z),
		quaternion: new Quaternion().setFromEuler(
			new Euler(MathUtils.degToRad(roll), MathUtils.degToRad(pitch), MathUtils.degToRad(yaw), 'ZYX'),
		),
	};
}
