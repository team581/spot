import type { Job } from './types';

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
	const response = await fetch(path, { ...options, credentials: 'same-origin' });
	const result = await response.json();
	if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
	return result as T;
}

/** One request ID per intent; a job is successful only after runtime acknowledgement. */
export async function submit(csrf: string, operation: string, payload: Record<string, unknown>): Promise<Job> {
	const request_id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (v) =>
		v.toString(16).padStart(2, '0'),
	).join('');
	const result = await api<{ job_id: string }>('/api/operations', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', 'X-Spot-CSRF': csrf },
		body: JSON.stringify({ operation, payload, request_id }),
	});
	for (let n = 0; n < (operation.startsWith('network/') ? 240 : 120); n++) {
		await new Promise((resolve) => setTimeout(resolve, 250));
		const job = await api<Job>('/api/jobs/' + result.job_id);
		if (job.state === 'rejected') throw new Error(job.error);
		if (job.state === 'applied') return job;
	}
	throw new Error('Acknowledgement pending; read current values before retrying');
}
