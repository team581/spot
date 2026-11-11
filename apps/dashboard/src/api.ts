import createClient from 'openapi-fetch';
import type { components, paths } from './api.gen';

type Schemas = components['schemas'];
export type CameraState = Schemas['CameraState'];
export type DeviceStatus = Schemas['DeviceStatus'];
export type CameraConfig = Schemas['CameraConfig'];
export type ControlRange = Schemas['ControlRange'];
export type NetworkStatus = Schemas['NetworkStatus'];
export type AddressMode = Schemas['AddressMode'];
export type Settings = Schemas['Settings'];

export const client = createClient<paths>();

/** Resolves to the response body, or rejects with the service's error text. */
export async function unwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>) {
	const { data, error, response } = await request;
	if (!response.ok) throw new Error(typeof error === 'string' && error ? error : `HTTP ${response.status}`);
	return data as T;
}
