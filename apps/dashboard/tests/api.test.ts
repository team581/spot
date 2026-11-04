import { afterEach, expect, test, vi } from 'vite-plus/test';
import { api, submit } from '../src/api';
const response = (value: unknown, status = 200) =>
	new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
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
	const result = submit('csrf', 'tune', { name: 'front', revision: 'a', values: { gain: 2 } });
	await vi.runAllTimersAsync();
	await expect(result).resolves.toMatchObject({ state: 'applied', revision: 'b' });
	const [url, request] = fetch.mock.calls[0];
	expect(url).toBe('/api/operations');
	expect(request.credentials).toBe('same-origin');
	expect(request.headers).toEqual({ 'Content-Type': 'application/json', 'X-Spot-CSRF': 'csrf' });
	const body = JSON.parse(request.body);
	expect(body).toMatchObject({ operation: 'tune', payload: { name: 'front', revision: 'a', values: { gain: 2 } } });
	expect(body.request_id).toMatch(/^[a-f0-9]{32}$/);
	expect(fetch.mock.calls.slice(1).every(([path]) => path === '/api/jobs/job')).toBe(true);
});
test('a rejected job is reported without resubmitting the operation', async () => {
	vi.useFakeTimers();
	const fetch = vi
		.fn()
		.mockResolvedValueOnce(response({ job_id: 'job' }))
		.mockResolvedValue(response({ state: 'rejected', error: 'Revision conflict' }));
	vi.stubGlobal('fetch', fetch);
	const assertion = expect(submit('csrf', 'tune', {})).rejects.toThrow('Revision conflict');
	await vi.runAllTimersAsync();
	await assertion;
	expect(fetch).toHaveBeenCalledTimes(2);
});
test.each([
	['tune', 120],
	['network/apply', 240],
])('%s has a bounded acknowledgement wait', async (operation, attempts) => {
	vi.useFakeTimers();
	const fetch = vi
		.fn()
		.mockResolvedValueOnce(response({ job_id: 'job' }))
		.mockImplementation(async () => response({ state: 'pending' }));
	vi.stubGlobal('fetch', fetch);
	const assertion = expect(submit('csrf', operation, {})).rejects.toThrow('Acknowledgement pending');
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
