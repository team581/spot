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
	if (typeof value !== 'object' || value === null || Array.isArray(value) || value instanceof Date) {
		throw new Error(`${path} must be a table`);
	}
	const unknown = keys && Object.keys(value).find((key) => !keys.includes(key));
	if (unknown) {
		throw new Error(`${path} has unknown key "${unknown}"; expected one of ${keys.join(', ')}`);
	}
	// oxlint-disable-next-line typescript/no-unsafe-type-assertion -- The checks above establish an object with unknown property values.
	return value as Table;
}
interface Primitive {
	string: string;
	number: number;
	boolean: boolean;
}
function optional<T extends keyof Primitive>(value: unknown, type: T, path: string): Primitive[T] | undefined {
	if (value !== undefined && typeof value !== type) {
		throw new Error(`${path} must be a ${type}`);
	}
	// oxlint-disable-next-line typescript/no-unsafe-type-assertion -- typeof validates the primitive selected by the type argument.
	return value as Primitive[T] | undefined;
}

export function parseConfig(text: string): PreviewCamera[] {
	const cameras = table(parse(text).cameras ?? {}, 'cameras');
	return Object.entries(cameras).map(([name, value]) => {
		const path = `cameras.${name}`;
		const camera = table(value, path, cameraKeys);
		const mode = optional(camera.mode, 'string', `${path}.mode`) ?? '1280x800@120';
		const resolution = /^(?<resolution>\d+x\d+)@\d+$/.exec(mode)?.groups?.resolution;
		if (!resolution) {
			throw new Error(`${path}.mode must look like 1280x800@120, not "${mode}"`);
		}
		const mount = table(camera.mount ?? {}, `${path}.mount`, mountKeys);
		const controls = table(camera.controls ?? {}, `${path}.controls`, controlKeys);
		const calibrations = table(camera.calibrations ?? {}, `${path}.calibrations`);
		return {
			name,
			required: optional(camera.required, 'boolean', `${path}.required`) ?? false,
			serial: optional(camera.serial, 'string', `${path}.serial`),
			port: optional(camera.port, 'string', `${path}.port`),
			mode,
			resolution,
			controls: Object.fromEntries(
				Object.entries(controls).map(([key, control]) => {
					if (typeof control !== 'string' && typeof control !== 'number') {
						throw new TypeError(`${path}.controls.${key} must be a string or number`);
					}
					return [key, control];
				}),
			),
			// oxlint-disable-next-line typescript/no-unsafe-type-assertion -- Every mount key is present and its value is checked as a number below.
			mount: Object.fromEntries(
				mountKeys.map((key) => [key, optional(mount[key], 'number', `${path}.mount.${key}`) ?? 0]),
			) as PreviewCamera['mount'],
			calibrations: Object.keys(calibrations).toSorted(),
		};
	});
}
