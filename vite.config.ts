import { defineConfig } from 'vite-plus';
import fmt from './oxfmt.config.ts';
import lint from './oxlint.config.ts';
export default defineConfig({
	fmt,
	lint: {
		...lint,
		plugins: ['typescript', 'react', 'react-hooks'],
	},
});
