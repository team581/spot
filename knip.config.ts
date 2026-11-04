import type { KnipConfig } from 'knip';

const config: KnipConfig = {
	workspaces: {
		'.': {},
		'src/spot_vision/web': {
			// Python serves these browser scripts directly; tests live with the other tools.
			entry: ['*.js', '../../../tools/tests/*.cjs'],
			project: ['*.js', '../../../tools/tests/*.cjs'],
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
