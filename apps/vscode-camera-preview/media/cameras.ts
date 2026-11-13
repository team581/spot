import { quaternion } from '@spot/camera-viewer';
import type { Mount } from '@spot/camera-viewer';
import type { PreviewCamera } from '../config';

/** A camera's mount in the viewer's form; angles follow WPILib Rotation3d(roll, pitch, yaw). */
export function previewMount({ name, mount: { x, y, z, roll, pitch, yaw } }: PreviewCamera): Mount {
	return { name, quaternion: quaternion(yaw, pitch, roll), translation: [x, y, z] };
}
