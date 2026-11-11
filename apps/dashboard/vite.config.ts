import { defineConfig } from 'vite-plus';
import react from '@vitejs/plugin-react';
import { tanstackRouter } from '@tanstack/router-plugin/vite';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
const backend = process.env.SPOT_BACKEND || 'http://127.0.0.1:5808';
// The live camera views use the Foxglove WebSocket server on the same host.
const foxglove = Object.assign(new URL(backend), { protocol: 'ws:', port: '5801' }).origin;
export default defineConfig({
	plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
	resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
	build: { outDir: '../../dist/dashboard', emptyOutDir: true, assetsInlineLimit: 0 },
	server: {
		host: '127.0.0.1',
		proxy: {
			'/api': backend,
			'/docs': backend,
			'/recordings': backend,
			'/foxglove': { target: foxglove, ws: true, rewrite: () => '/' },
		},
	},
	test: {
		include: ['src/**/*.test.ts'],
		reporters: ['default', 'junit'],
		outputFile: { junit: 'test-results/unit-junit.xml' },
	},
});
