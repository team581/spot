import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import mdx from '@astrojs/mdx';
import { satteri } from '@astrojs/markdown-satteri';
import team581Theme from '@team581/starlight-theme';
import { render } from 'pele';

const jetson = process.env.DOCS_TARGET === 'jetson';
const base = jetson ? '/docs/' : '/';
// The Jetson dashboard shows these pages in a pane; follow its theme and open other pages outside the pane.
const embedded = `if (window.top !== window.self) {
	const root = document.documentElement;
	root.dataset.embedded = '';
	// Frames blank between pages unless a view transition holds the old page until the new one paints.
	const transitions = document.createElement('style');
	transitions.textContent = '@view-transition { navigation: auto; }';
	document.head.append(transitions);
	const sync = () => {
		let preference = 'auto';
		try {
			preference = (localStorage.getItem('spot-theme') || 'auto').toLowerCase();
			localStorage.setItem('starlight-theme', preference === 'auto' ? '' : preference);
		} catch {}
		root.dataset.theme =
			preference === 'auto' ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : preference;
	};
	sync();
	addEventListener('storage', (event) => event.key === 'spot-theme' && sync());
	document.addEventListener('click', (event) => {
		const link = event.target instanceof Element && event.target.closest('a[href]');
		if (link && !link.href.startsWith(location.origin + '${base}')) link.target = '_top';
	});
}`;

export default defineConfig({
	site: 'https://spot.frc581.com',
	base,
	trailingSlash: 'always',
	outDir: jetson ? '../../dist/jetson-docs' : '../../dist/docs',
	markdown: {
		processor: satteri({
			features: { rawHtml: true },
			mdastPlugins: [
				{
					name: 'pele',
					code(node) {
						if (node.lang !== 'mermaid') return;
						const { svg } = render(node.value, { idPrefix: `pele-${node.position?.start.offset}` });
						return { type: 'html', value: `<div class="diagram">${svg}</div>` };
					},
				},
			],
		}),
	},
	integrations: [
		starlight({
			title: 'Spot documentation',
			description: "Team 581's Jetson vision system: setup, calibration, and robot integration.",
			favicon: '/favicon.svg',
			social: [
				...(jetson ? [{ icon: 'left-arrow' as const, label: 'Dashboard', href: '/' }] : []),
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/team581/spot' },
			],
			plugins: [team581Theme()],
			customCss: ['./src/styles/diagrams.css', './src/styles/embedded.css'],
			head: jetson ? [{ tag: 'script', content: embedded }] : [],
			sidebar: [
				{ slug: 'index', label: 'Overview' },
				{ slug: 'downloads', label: 'Downloads' },
				{ slug: 'robot-config', label: 'Robot configuration' },
				{ slug: 'operator/cameras', label: 'Camera setup' },
				{ slug: 'operator/deployment', label: 'Jetson installation and recovery' },
				{ slug: 'development', label: 'Development' },
				{ slug: 'operator/vscode-camera-preview', label: 'VS Code camera preview' },
			],
		}),
		mdx(),
	],
});
