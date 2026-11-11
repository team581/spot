import { defineConfig } from 'vite-plus';
export default defineConfig({
	pack: {
		entry: ['extension.ts'],
		format: ['cjs'],
		outDir: 'out',
		target: 'node20',
		dts: false,
		// The VSIX ships without node_modules.
		deps: { neverBundle: ['vscode'], alwaysBundle: ['smol-toml'] },
	},
	build: {
		outDir: 'media',
		emptyOutDir: false,
		lib: {
			entry: 'media/preview.ts',
			formats: ['iife'],
			name: 'SpotCameraPreview',
			fileName: () => 'preview.bundle.js',
		},
	},
});
