import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import mdx from '@astrojs/mdx';
import { satteri } from '@astrojs/markdown-satteri';
import team581Theme from '@team581/starlight-theme';
import { render } from 'pele';

const jetson = process.env.DOCS_TARGET === 'jetson';
const base = jetson ? '/docs/' : '/';
// The Jetson dashboard shows these pages in a pane; follow the system theme and open other pages outside the pane.
const embedded = `if (window.top !== window.self) {
	const root = document.documentElement;
	root.dataset.embedded = '';
	// Frames blank between pages unless a view transition holds the old page until the new one paints.
	const transitions = document.createElement('style');
	transitions.textContent = '@view-transition { navigation: auto; }';
	document.head.append(transitions);
	// The dashboard follows the system theme, so drop any theme saved from the docs site.
	try {
		localStorage.removeItem('starlight-theme');
	} catch {}
	root.dataset.theme = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
	document.addEventListener('click', (event) => {
		const link = event.target instanceof Element && event.target.closest('a[href]');
		if (link && !link.href.startsWith(location.origin + '${base}')) link.target = '_top';
	});
}`;

export default defineConfig({
	base,
	integrations: [
		starlight({
			customCss: ['./src/styles/diagrams.css', './src/styles/embedded.css'],
			description: "Team 581's Jetson vision system: setup, calibration, and robot integration.",
			favicon: '/favicon.svg',
			head: jetson ? [{ tag: 'script', content: embedded }] : [],
			logo: { light: './src/assets/logo-tight.svg', dark: './src/assets/logo-tight-dark.svg' },
			plugins: [team581Theme()],
			sidebar: [
				{ slug: 'index', label: 'Overview' },
				{
					label: 'How-to guides',
					items: [
						'how-to/set-up-jetson',
						'how-to/add-camera',
						'how-to/calibrate',
						'how-to/save-dashboard-changes',
						'how-to/review-recording',
						'how-to/change-network',
						'how-to/preview-mounts-in-vscode',
						'how-to/update',
						'how-to/develop',
					],
				},
				{
					label: 'Reference',
					items: ['reference/config', 'reference/networktables', 'reference/java-client', 'reference/jetson'],
				},
				{ label: 'Explanation', items: ['explanation/pose-estimates', 'explanation/config'] },
			],
			social: [
				...(jetson ? [{ icon: 'left-arrow' as const, label: 'Dashboard', href: '/' }] : []),
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/team581/spot' },
			],
			title: 'Spot documentation',
		}),
		mdx(),
	],
	markdown: {
		processor: satteri({
			features: { rawHtml: true },
			mdastPlugins: [
				{
					code(node) {
						if (node.lang !== 'mermaid') {
							return undefined;
						}
						const { svg } = render(node.value, { idPrefix: `pele-${node.position?.start.offset}` });
						return { type: 'html', value: `<div class="diagram">${svg}</div>` };
					},
					name: 'pele',
				},
			],
		}),
	},
	outDir: jetson ? '../../dist/jetson-docs' : '../../dist/docs',
	site: 'https://spot.frc581.com',
	trailingSlash: 'always',
});
