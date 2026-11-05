import { quaternion } from '@spot/camera-viewer';
import type { SpotCamera } from '../profile';
/** A camera's mount in the viewer's form; angles follow WPILib Rotation3d(roll, pitch, yaw). */
export function previewMount(camera: SpotCamera) {
	const { x_m = 0, y_m = 0, z_m = 0, roll_deg = 0, pitch_deg = 0, yaw_deg = 0 } = camera.robot_to_camera ?? {};
	return {
		name: camera.name,
		translation: [x_m, y_m, z_m],
		rollPitchYawDeg: [roll_deg, pitch_deg, yaw_deg],
		quaternion: quaternion(yaw_deg, pitch_deg, roll_deg),
	};
}
