import type { KnipConfig } from 'knip';

const config: KnipConfig = {
	workspaces: {
		'.': {},
		'apps/dashboard': {
			// Python serves these browser scripts directly.
			entry: ['*.js', 'tests/*.cjs'],
			project: ['*.js', 'tests/*.cjs'],
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
