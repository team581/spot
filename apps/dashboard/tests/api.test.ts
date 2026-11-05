import { afterEach, beforeEach, expect, test, vi } from 'vite-plus/test';
import { api, submit } from '../src/api';
const response = (value: unknown, status = 200) =>
	new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const tune = { name: 'front', revision: 'a', values: { gain: 2 } };
beforeEach(() => {
	vi.stubGlobal('location', { origin: 'http://spot.local:5800' });
});
afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});
test('mutation sends session CSRF and one bounded request ID, then waits for an applied job', async () => {
	vi.useFakeTimers();
	const fetch = vi
		.fn()
		.mockResolvedValueOnce(response({ job_id: 'job' }))
		.mockResolvedValueOnce(response({ state: 'pending' }))
		.mockResolvedValueOnce(response({ state: 'applied', revision: 'b' }));
	vi.stubGlobal('fetch', fetch);
	const result = submit('csrf', 'tune', tune);
	await vi.runAllTimersAsync();
	await expect(result).resolves.toMatchObject({ state: 'applied', revision: 'b' });
	const request: Request = fetch.mock.calls[0][0];
	expect(request.url).toBe('http://spot.local:5800/api/operations');
	expect(request.credentials).toBe('same-origin');
	expect(request.headers.get('Content-Type')).toBe('application/json');
	expect(request.headers.get('X-Spot-CSRF')).toBe('csrf');
	const body = await request.json();
	expect(body).toMatchObject({ operation: 'tune', payload: tune });
	expect(body.request_id).toMatch(/^[a-f0-9]{32}$/);
	expect(fetch.mock.calls.slice(1).every(([job]) => job.url === 'http://spot.local:5800/api/jobs/job')).toBe(true);
});
test('a rejected job is reported without resubmitting the operation', async () => {
	vi.useFakeTimers();
	const fetch = vi
		.fn()
		.mockResolvedValueOnce(response({ job_id: 'job' }))
		.mockResolvedValue(response({ state: 'rejected', error: 'Revision conflict' }));
	vi.stubGlobal('fetch', fetch);
	const assertion = expect(submit('csrf', 'tune', tune)).rejects.toThrow('Revision conflict');
	await vi.runAllTimersAsync();
	await assertion;
	expect(fetch).toHaveBeenCalledTimes(2);
});
test.each([
	['tune', tune, 120],
	['network/apply', { mode: 'static', address: '10.5.81.11/24' }, 240],
] as const)('%s has a bounded acknowledgement wait', async (operation, payload, attempts) => {
	vi.useFakeTimers();
	const fetch = vi
		.fn()
		.mockResolvedValueOnce(response({ job_id: 'job' }))
		.mockImplementation(async () => response({ state: 'pending' }));
	vi.stubGlobal('fetch', fetch);
	const assertion = expect(submit('csrf', operation, payload)).rejects.toThrow('Acknowledgement pending');
	await vi.runAllTimersAsync();
	await assertion;
	expect(fetch).toHaveBeenCalledTimes(attempts + 1);
});
test('HTTP failures preserve the service error', async () => {
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => response({ error: 'Session/CSRF check failed' }, 403)),
	);
	await expect(api('/api/operations')).rejects.toThrow('Session/CSRF check failed');
});
