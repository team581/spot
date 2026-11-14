import { defineConfig } from 'vite-plus';

export default defineConfig({
	pack: {
		dts: true,
		entry: ['src/index.ts'],
		format: ['esm'],
		// Left for the consuming app's bundler to resolve.
		deps: { neverBundle: [/\.glb\?url$/] },
		copy: [{ from: 'src/camera.glb', to: 'dist' }],
	},
	test: { setupFiles: ['test/setup.ts'] },
});
