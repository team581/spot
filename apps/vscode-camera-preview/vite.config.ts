import { defineConfig } from 'vite-plus';

export default defineConfig({
	build: {
		emptyOutDir: false,
		lib: {
			entry: 'media/preview.ts',
			fileName: () => 'preview.bundle.js',
			formats: ['iife'],
			name: 'SpotCameraPreview',
		},
		outDir: 'media',
	},
	pack: {
		entry: ['extension.ts'],
		format: ['cjs'],
		outDir: 'out',
		target: 'node20',
		dts: false,
		// The VSIX ships without node_modules.
		deps: { alwaysBundle: ['smol-toml'], neverBundle: ['vscode'] },
	},
});
