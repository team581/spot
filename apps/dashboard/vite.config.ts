import { defineConfig } from 'vite-plus';
import react from '@vitejs/plugin-react';
import { tanstackRouter } from '@tanstack/router-plugin/vite';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';

const backend = process.env.SPOT_BACKEND ?? 'http://127.0.0.1:5808';
// The live camera views use the Foxglove WebSocket server on the same host.
const foxglove = Object.assign(new URL(backend), { port: '5801', protocol: 'ws:' }).origin;
export default defineConfig({
	build: { assetsInlineLimit: 0, emptyOutDir: true, outDir: '../../dist/dashboard' },
	plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
	resolve: { alias: { '@': fileURLToPath(new URL('src', import.meta.url)) } },
	server: {
		host: '127.0.0.1',
		// The router plugin regenerates the route tree when route files change. Ignoring the tree itself
		// This prevents the plugin from rewriting it when something else writes it, like hk restoring it mid-commit.
		// Previously, the tree was restored before the untracked routes it depends on, which made hk's restore fail.
		watch: { ignored: ['**/src/routeTree.gen.ts'] },
		proxy: {
			'/api': backend,
			'/docs': backend,
			'/recordings': backend,
			'/foxglove': { target: foxglove, ws: true, rewrite: () => '/' },
		},
	},
	test: {
		include: ['src/**/*.test.ts'],
		outputFile: { junit: 'test-results/unit-junit.xml' },
		reporters: ['default', 'junit'],
	},
});
