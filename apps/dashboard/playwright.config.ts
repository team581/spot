import { createServer } from 'node:net';
import { defineConfig } from '@playwright/test';
const freePort = () =>
	new Promise<string>((resolve) => {
		const server = createServer().listen(0, '127.0.0.1', () => {
			const { port } = server.address() as { port: number };
			server.close(() => resolve(String(port)));
		});
	});
// Workers inherit these from the runner, so every process agrees on the ports.
process.env.SPOT_TEST_PORT ||= await freePort();
process.env.SPOT_TEST_DEV_PORT ||= await freePort();
const backend = 'http://127.0.0.1:' + process.env.SPOT_TEST_PORT,
	dev = 'http://127.0.0.1:' + process.env.SPOT_TEST_DEV_PORT;
export default defineConfig({
	testDir: './tests/browser',
	workers: 1,
	timeout: 20000,
	globalTimeout: process.env.CI ? 5 * 60 * 1000 : undefined,
	reporter: process.env.CI ? [['list'], ['junit', { outputFile: 'test-results/junit.xml' }]] : 'list',
	use: {
		viewport: { width: 1440, height: 1000 },
		trace: 'retain-on-failure',
	},
	projects: [
		{ name: 'production', testMatch: '**/behavior.spec.ts', use: { baseURL: backend } },
		{ name: 'development', testMatch: '**/development.spec.ts', use: { baseURL: dev } },
	],
	webServer: [
		{
			command: '../../.venv/bin/python tests/serve.py',
			url: backend + '/api/status',
			reuseExistingServer: false,
		},
		{
			command: `pnpm dev --port ${process.env.SPOT_TEST_DEV_PORT} --strictPort`,
			url: dev,
			env: { SPOT_BACKEND: backend },
			reuseExistingServer: false,
		},
	],
});
