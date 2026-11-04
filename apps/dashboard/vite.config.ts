import { defineConfig } from 'vite-plus';
import react from '@vitejs/plugin-react';
const backend = process.env.SPOT_BACKEND || 'http://127.0.0.1:5808';
export default defineConfig({
	plugins: [react()],
	// The shared renderer is a linked CommonJS workspace also consumed by VS Code.
	optimizeDeps: { include: ['@spot/camera-viewer'] },
	build: { outDir: '../../dist/dashboard', emptyOutDir: true, assetsInlineLimit: 0 },
	server: {
		host: '127.0.0.1',
		port: 5815,
		strictPort: true,
		proxy: {
			'/api': {
				target: backend,
				changeOrigin: true,
				configure(proxy) {
					proxy.on('proxyReq', (req) => {
						if (req.getHeader('origin')) req.setHeader('Origin', backend);
					});
				},
			},
			'/docs': { target: backend, changeOrigin: true },
		},
	},
	test: { include: ['src/**/*.test.ts', 'tests/*.test.{ts,js}'] },
});
