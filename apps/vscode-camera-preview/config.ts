import { parse } from 'smol-toml';

/** The parts of robot code's spot.toml the preview shows; Spot validates the whole file. */
export interface PreviewCamera {
	name: string;
	required: boolean;
	serial?: string;
	port?: string;
	/** Capture mode as written, `WIDTHxHEIGHT@FPS`. */
	mode: string;
	/** `WIDTHxHEIGHT`, the key calibrations use. */
	resolution: string;
	controls: Record<string, string | number>;
	/** Meters and degrees, as WPILib `Transform3d` and `Rotation3d`. */
	mount: Record<(typeof mountKeys)[number], number>;
	/** Resolutions with a calibration. */
	calibrations: string[];
}

const cameraKeys = ['serial', 'port', 'required', 'mode', 'controls', 'mount', 'calibrations'];
const controlKeys = ['auto_exposure', 'exposure_time_absolute', 'gain'];
const mountKeys = ['x', 'y', 'z', 'roll', 'pitch', 'yaw'] as const;

type Table = Record<string, unknown>;
function table(value: unknown, path: string, keys?: readonly string[]): Table {
	if (typeof value !== 'object' || value === null || Array.isArray(value) || value instanceof Date)
		throw Error(`${path} must be a table`);
	const unknown = keys && Object.keys(value).find((key) => !keys.includes(key));
	if (unknown) throw Error(`${path} has unknown key "${unknown}"; expected one of ${keys.join(', ')}`);
	return value as Table;
}
function optional<T>(value: unknown, type: string, path: string): T | undefined {
	if (value !== undefined && typeof value !== type) throw Error(`${path} must be a ${type}`);
	return value as T | undefined;
}

export function parseConfig(text: string): PreviewCamera[] {
	const cameras = table(parse(text).cameras ?? {}, 'cameras');
	return Object.entries(cameras).map(([name, value]) => {
		const path = `cameras.${name}`,
			camera = table(value, path, cameraKeys),
			mode = optional<string>(camera.mode, 'string', `${path}.mode`) ?? '1280x800@120',
			resolution = /^(\d+x\d+)@\d+$/.exec(mode)?.[1];
		if (!resolution) throw Error(`${path}.mode must look like 1280x800@120, not "${mode}"`);
		const mount = table(camera.mount ?? {}, `${path}.mount`, mountKeys),
			controls = table(camera.controls ?? {}, `${path}.controls`, controlKeys),
			calibrations = table(camera.calibrations ?? {}, `${path}.calibrations`);
		return {
			name,
			required: optional<boolean>(camera.required, 'boolean', `${path}.required`) ?? false,
			serial: optional<string>(camera.serial, 'string', `${path}.serial`),
			port: optional<string>(camera.port, 'string', `${path}.port`),
			mode,
			resolution,
			controls: controls as PreviewCamera['controls'],
			mount: Object.fromEntries(
				mountKeys.map((key) => [key, optional<number>(mount[key], 'number', `${path}.mount.${key}`) ?? 0]),
			) as PreviewCamera['mount'],
			calibrations: Object.keys(calibrations).sort(),
		};
	});
}
