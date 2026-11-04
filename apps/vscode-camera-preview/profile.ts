interface PreviewCamera {
	name: string;
	translation: number[];
	quaternion: number[];
	required: boolean;
	imageRotationDeg: number;
	capture: { width: number; height: number; fps: number; pixelFormat: string }[];
	controls: { name: string; value: number; required: boolean; allowOverride: boolean }[];
}
export interface PreviewProfile {
	schemaVersion: 1;
	robotId: string;
	cameras: PreviewCamera[];
}
export function parseProfile(text: string): PreviewProfile {
	const data = JSON.parse(text) as PreviewProfile;
	if (data.schemaVersion !== 1 || !Array.isArray(data.cameras)) throw Error('Unsupported preview format');
	return data;
}
