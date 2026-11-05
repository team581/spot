/** The parts of robot code's spot-config.json the preview shows; Spot validates the whole file. */
export interface SpotConfig {
	cameras: SpotCamera[];
}
export interface SpotCamera {
	name: string;
	required?: boolean;
	image_rotation_deg?: number;
	robot_to_camera?: Partial<Record<'x_m' | 'y_m' | 'z_m' | 'roll_deg' | 'pitch_deg' | 'yaw_deg', number>>;
	allowed_modes?: { width: number; height: number; fps: number; pixel_format: string }[];
	controls?: { name: string; default_value: number; required?: boolean; allow_override?: boolean }[];
}
export function parseConfig(text: string): SpotConfig {
	const data = JSON.parse(text) as SpotConfig;
	if (!Array.isArray(data?.cameras)) throw Error('spot-config.json needs a cameras array');
	return data;
}
