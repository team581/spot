import type { KnipConfig } from 'knip';

const config: KnipConfig = {
	workspaces: {
		'.': {},
		'apps/dashboard': {
			// Browser behavior tests are run separately by Playwright.
			entry: ['tests/*.test.js', 'tests/browser/*.ts'],
			project: ['src/**/*.{ts,tsx}', '*.ts', 'tests/**/*.{ts,js,cjs}'],
		},
		'apps/docs': {},
		'packages/camera-viewer': {},
		'apps/vscode-camera-preview': {
			entry: ['test/*.cjs'],
			project: ['*.{ts,mts,cjs}', 'media/*.ts', 'test/**/*.cjs'],
		},
	},
};

export default config;
