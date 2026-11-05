import { defineConfig } from 'vite-plus';
import react from '@vitejs/plugin-react';
const backend = process.env.SPOT_BACKEND || 'http://127.0.0.1:5808';
export default defineConfig({
	plugins: [react()],
	build: { outDir: '../../dist/dashboard', emptyOutDir: true, assetsInlineLimit: 0 },
	server: {
		host: '127.0.0.1',
		port: 5815,
		strictPort: true,
		proxy: {
			'/api': {
				target: backend,
				changeOrigin: true,
				ws: true,
				configure(proxy) {
					// The service only accepts writes and streams from its own origin.
					const origin = (req: { getHeader(name: string): unknown; setHeader(name: string, value: string): void }) => {
						if (req.getHeader('origin')) req.setHeader('Origin', backend);
					};
					proxy.on('proxyReq', origin);
					proxy.on('proxyReqWs', origin);
				},
			},
			'/docs': { target: backend, changeOrigin: true },
		},
	},
	test: {
		include: ['src/**/*.test.ts', 'tests/*.test.{ts,js}'],
		reporters: ['default', 'junit'],
		outputFile: { junit: 'test-results/unit-junit.xml' },
	},
});
