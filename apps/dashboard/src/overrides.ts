import { parse } from 'smol-toml';
import { z } from 'zod';

export type Json = z.infer<ReturnType<typeof z.json>>;
/** A deep-partial robot config: objects merge key by key, `null` removes a key, other values replace. */
export type Overrides = Record<string, Json>;

const overridesSchema = z.record(z.string(), z.json());

/** Parse the JSON-compatible TOML values accepted by Spot's config API. */
export function parseOverrides(text: string): Overrides {
	const result = overridesSchema.safeParse(parse(text));
	if (!result.success) {
		throw new Error('Config values must be JSON-compatible: dates and non-finite numbers are not supported.');
	}
	return result.data;
}

const isObject = (value: Json | undefined): value is Record<string, Json> =>
	typeof value === 'object' && value !== null && !Array.isArray(value);

/** Returns a copy of `overrides` with `value` at `path`, replacing anything in the way that isn't an object. */
export function setOverride(overrides: Overrides, path: string[], value: Json): Overrides {
	const [key, ...rest] = path;
	if (key === undefined) {
		return overrides;
	}
	const child = overrides[key];
	return { ...overrides, [key]: rest.length > 0 ? setOverride(isObject(child) ? child : {}, rest, value) : value };
}

export interface Difference {
	path: string;
	before: Json | undefined;
	after: Json;
}

/** Lists each overridden value next to the robot config's value at the same path. */
export function diffOverrides(robot: Json | undefined, overrides: Overrides, prefix = ''): Difference[] {
	return Object.entries(overrides).flatMap(([key, after]) => {
		const path = prefix + key;
		const before = isObject(robot) ? robot[key] : undefined;
		return isObject(after) ? diffOverrides(before, after, `${path}.`) : [{ after, before, path }];
	});
}

/** Returns overrides that turn the robot config into `target`. Spot prunes the ones the robot config already matches. */
export function overridesFor(robot: Json | undefined, target: Overrides): Overrides {
	const removed = isObject(robot) ? Object.keys(robot).filter((key) => !(key in target)) : [];
	return Object.fromEntries([
		...removed.map((key) => [key, null]),
		...Object.entries(target).map(([key, value]) => {
			const before = isObject(robot) ? robot[key] : undefined;
			return [key, isObject(value) && isObject(before) ? overridesFor(before, value) : value];
		}),
	]);
}
