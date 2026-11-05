import type { Camera, Override } from '../types';

const settings: Record<string, string> = {
	robot_to_camera: 'Mount',
	calibration: 'Calibration',
	timestamp_qualification: 'Timestamp qualification',
	allowed_modes: 'Capture mode',
	binding_id: 'Physical camera',
	enabled: 'Enabled',
	image_rotation_deg: 'Image rotation',
};

/** Count with a singular or plural noun, as in `1 change` or `2 changes`. */
export const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** Path of a camera control's override, as reported in `status.overrides`. */
export const controlPath = (camera: string, control: string) => `cameras/${camera}/controls/${control}`;

/** Readable camera and setting names for an override path. */
export function describe(path: string, cameras: Camera[]): { camera?: string; setting: string } {
	const [group, name, key, control] = path.split('/');
	if (group !== 'cameras') return { setting: path.split('/').join(' · ') };
	if (key === 'controls') {
		const label = cameras.find((c) => c.logical_name === name)?.controls?.find((c) => c.name === control)?.label;
		return { camera: name, setting: label ?? control };
	}
	return { camera: name, setting: settings[key] ?? path.split('/').slice(2).join(' · ') };
}

/** Short display text for one side of an override. */
export function display(path: string, value: unknown): string {
	if (value == null) return 'Not set';
	const key = path.split('/')[2];
	const v = value as Record<string, unknown> & unknown[];
	if (key === 'controls') return String(v.default_value);
	if (key === 'robot_to_camera')
		return (
			['x_m', 'y_m', 'z_m'].map((k) => Number(v[k]).toFixed(3)).join(', ') +
			' m · ' +
			['roll_deg', 'pitch_deg', 'yaw_deg'].map((k) => Number(v[k]).toFixed(1)).join(', ') +
			'°'
		);
	if (key === 'calibration') return 'Calibrated';
	if (key === 'allowed_modes') {
		const mode = v[0] as { width: number; height: number; fps: number } | undefined;
		return mode ? `${mode.width} × ${mode.height} · ${mode.fps} FPS` : 'None';
	}
	return typeof value === 'string' ? value : JSON.stringify(value);
}

export const isOverride = (overrides: Override[] | undefined, path: string) => overrides?.find((o) => o.path === path);
