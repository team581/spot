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
// Failed requests reject with the service's error text, including ones with an empty body.
client.use({
	async onResponse({ response }) {
		if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
	},
});
