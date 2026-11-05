import { afterEach, beforeEach, expect, test, vi } from 'vite-plus/test';
import { api, submit } from '../src/api';
const response = (value: unknown, status = 200) =>
	new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const tune = { name: 'front', revision: 'a', values: { gain: 2 } };
beforeEach(() => {
	vi.stubGlobal('location', { origin: 'http://spot.local:5800' });
});
afterEach(() => {
	vi.unstubAllGlobals();
});
test('an operation posts its JSON payload to its own route and returns the acknowledgement', async () => {
	const fetch = vi.fn().mockResolvedValue(response({ revision: 'b', applied_generation: 'b' }));
	vi.stubGlobal('fetch', fetch);
	await expect(submit('camera/tune', tune)).resolves.toEqual({ revision: 'b', applied_generation: 'b' });
	const request: Request = fetch.mock.calls[0][0];
	expect(request.method).toBe('POST');
	expect(request.url).toBe('http://spot.local:5800/api/camera/tune');
	expect(request.credentials).toBe('same-origin');
	expect(request.headers.get('Content-Type')).toBe('application/json');
	expect(await request.json()).toEqual(tune);
});
test('HTTP failures preserve the service error', async () => {
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => response({ error: 'revision conflict; fetch current configuration' }, 400)),
	);
	await expect(submit('camera/tune', tune)).rejects.toThrow('revision conflict');
	await expect(api('/api/status')).rejects.toThrow('revision conflict');
});
