import type { KnipConfig } from 'knip';

const config: KnipConfig = {
	workspaces: {
		'.': {},
		'apps/dashboard': {
			project: ['src/**/*.{ts,tsx}', '*.ts'],
			// Generated schemas export their complete types and descriptors.
			ignore: ['src/api.gen.ts', 'src/gen/**'],
			// Vendored by the shadcn CLI; keep components whole so `shadcn add` updates stay clean.
			ignoreIssues: { 'src/components/ui/**': ['exports'] },
		},
		'apps/docs': {},
		'apps/vscode-camera-preview': {
			entry: ['test/*.test.ts'],
			project: ['*.{ts,mts,cjs}', 'media/*.ts', 'test/**/*.ts'],
		},
		'packages/camera-viewer': {},
	},
};

export default config;
