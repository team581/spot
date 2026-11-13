import { parse } from 'smol-toml';
import { z } from 'zod';

const control = z.union([z.string(), z.number()], { error: 'must be a string or number' });
const table = z.record(z.string(), z.unknown());
const cameraSchema = table
	.pipe(
		z.strictObject({
			serial: z.string().optional(),
			port: z.string().optional(),
			required: z.boolean().default(false),
			/** Capture mode as written, `WIDTHxHEIGHT@FPS`. */
			mode: z
				.string()
				.regex(/^\d+x\d+@\d+$/, 'must look like 1280x800@120')
				.default('1280x800@120'),
			controls: table
				.pipe(
					z.strictObject({
						auto_exposure: control.optional(),
						exposure_time_absolute: control.optional(),
						gain: control.optional(),
					}),
				)
				.prefault({}),
			/** Meters and degrees, as WPILib `Transform3d` and `Rotation3d`. */
			mount: table
				.pipe(
					z.strictObject({
						x: z.number().default(0),
						y: z.number().default(0),
						z: z.number().default(0),
						roll: z.number().default(0),
						pitch: z.number().default(0),
						yaw: z.number().default(0),
					}),
				)
				.prefault({}),
			calibrations: z.record(z.string(), z.unknown()).default({}),
		}),
	)
	.transform(({ mode, calibrations, ...camera }) => ({
		...camera,
		mode,
		/** `WIDTHxHEIGHT`, the key calibrations use. */
		resolution: mode.split('@')[0],
		/** Resolutions with a calibration. */
		calibrations: Object.keys(calibrations).toSorted(),
	}));
const configSchema = z.object({ cameras: z.record(z.string(), cameraSchema).default({}) });

/** The parts of robot code's spot.toml the preview shows; Spot validates the whole file. */
export type PreviewCamera = z.infer<typeof cameraSchema> & { name: string };

export function parseConfig(text: string): PreviewCamera[] {
	const result = configSchema.safeParse(parse(text));
	if (!result.success) {
		throw new Error(z.prettifyError(result.error));
	}
	return Object.entries(result.data.cameras).map(([name, camera]) => Object.assign(camera, { name }));
}
