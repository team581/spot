import { defineConfig } from 'vite-plus';
export default defineConfig({
	fmt: {
		singleQuote: true,
		useTabs: true,
		printWidth: 120,
		ignorePatterns: [
			'**/node_modules/**',
			'**/out/**',
			'**/.astro/**',
			'apps/vscode-camera-preview/media/preview.bundle.js',
		],
	},
	lint: {
		categories: {
			correctness: 'error',
			perf: 'error',
		},
		ignorePatterns: ['**/out/**', 'apps/vscode-camera-preview/media/preview.bundle.js'],
		rules: {
			'no-await-in-loop': 'off',
			'no-unused-expressions': [
				'error',
				{
					allowShortCircuit: true,
					allowTernary: true,
				},
			],
			'typescript/no-non-null-asserted-optional-chain': 'error',
		},
		options: {
			typeAware: true,
			typeCheck: true,
		},
		plugins: ['typescript', 'react', 'react-hooks'],
	},
});
