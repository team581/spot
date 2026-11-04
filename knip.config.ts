import type { KnipConfig } from 'knip';

const config: KnipConfig = {
	workspaces: {
		'.': {
			// Browser scripts are loaded by Python-served HTML, outside a JS bundler.
			entry: ['src/spot_vision/web/*.js', 'tools/tests/*.cjs'],
			project: ['src/spot_vision/web/*.js', 'tools/tests/*.cjs'],
		},
		'docs-site': {},
		'tools/vscode-camera-preview': {
			// Invoked through pnpm exec from the VSIX packaging helper.
			ignoreDependencies: ['@vscode/vsce'],
			// VS Code loads the extension; packaging and private releases are explicit scripts.
			entry: ['release.cjs', 'media/*.js', 'test/*.cjs'],
			project: ['*.{ts,cjs}', 'media/*.js', 'test/*.cjs'],
		},
	},
};

export default config;
