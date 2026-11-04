import { defineConfig } from '@playwright/test';
export default defineConfig({
	testDir: './tests/browser',
	workers: 1,
	timeout: 20000,
	use: { viewport: { width: 1440, height: 1000 } },
	projects: [
		{ name: 'production', testMatch: '**/behavior.spec.ts', use: { baseURL: 'http://127.0.0.1:5818' } },
		{ name: 'development', testMatch: '**/development.spec.ts', use: { baseURL: 'http://127.0.0.1:5815' } },
	],
	webServer: [
		{
			command: '../../.venv/bin/python tests/serve.py',
			url: 'http://127.0.0.1:5818/api/status',
			reuseExistingServer: false,
		},
		{
			command: 'pnpm dev',
			url: 'http://127.0.0.1:5815',
			env: { SPOT_BACKEND: 'http://127.0.0.1:5818' },
			reuseExistingServer: false,
		},
	],
});
