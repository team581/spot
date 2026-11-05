import { up } from 'up-fetch';
import type { components, paths } from './api.gen';
import type { Job } from './types';

type Operation = paths['/api/operations']['post']['requestBody']['content']['application/json'];
export type OperationName = Operation['operation'];
export type OperationPayload<N extends OperationName> = Extract<Operation, { operation: N }>['payload'];

/** Same-origin JSON client. Rejections carry the service's `error` message. */
export const api = up(
	(input: RequestInfo | URL, init?: RequestInit) => fetch(input, init),
	() => ({
		baseUrl: location.origin,
		credentials: 'same-origin',
		parseRejected: async (response: Response) => new Error((await response.json()).error || `HTTP ${response.status}`),
	}),
);

/** One request ID per intent; a job is successful only after runtime acknowledgement. */
export async function submit<N extends OperationName>(
	csrf: string,
	operation: N,
	payload: OperationPayload<N>,
): Promise<Job> {
	const request_id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (v) =>
		v.toString(16).padStart(2, '0'),
	).join('');
	const result = await api<components['schemas']['JobAccepted']>('/api/operations', {
		method: 'POST',
		headers: { 'X-Spot-CSRF': csrf },
		body: { operation, payload, request_id },
	});
	for (let n = 0; n < (operation.startsWith('network/') ? 240 : 120); n++) {
		await new Promise((resolve) => setTimeout(resolve, 250));
		const job = await api<Job>('/api/jobs/' + result.job_id);
		if (job.state === 'rejected') throw new Error(job.error);
		if (job.state === 'applied') return job;
	}
	throw new Error('Acknowledgement pending; read current values before retrying');
}
