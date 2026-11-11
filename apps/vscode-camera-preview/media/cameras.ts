import { quaternion, type Mount } from '@spot/camera-viewer';
import type { PreviewCamera } from '../config';

/** A camera's mount in the viewer's form; angles follow WPILib Rotation3d(roll, pitch, yaw). */
export function previewMount({ name, mount: { x, y, z, roll, pitch, yaw } }: PreviewCamera): Mount {
	return { name, translation: [x, y, z], quaternion: quaternion(yaw, pitch, roll) };
}
