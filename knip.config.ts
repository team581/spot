import type { KnipConfig } from 'knip';

const config: KnipConfig = {
	workspaces: {
		'.': {},
		'apps/dashboard': {
			// Legacy alpha UI tests still run with node:test.
			entry: ['tests/*.cjs', 'tests/*.test.js', 'tests/browser/*.ts'],
			project: ['src/**/*.{ts,tsx}', '*.ts', 'tests/**/*.{ts,js,cjs}'],
		},
		'apps/docs': {},
		'packages/camera-viewer': {},
		'apps/vscode-camera-preview': {
			// Invoked through pnpm exec from the VSIX packaging helper.
			ignoreDependencies: ['@vscode/vsce'],
			// VS Code loads the extension; packaging and private releases are explicit scripts.
			entry: ['release.cjs', 'media/*.js', 'test/*.cjs'],
			project: ['*.{ts,cjs}', 'media/*.js', 'test/*.cjs'],
		},
	},
};

export default config;
