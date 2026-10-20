import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import mdx from '@astrojs/mdx';
import { satteri } from '@astrojs/markdown-satteri';
import team581Theme from '@team581/starlight-theme';
import mermaid from 'astro-mermaid';

const jetson = process.env.DOCS_TARGET === 'jetson';
const base = jetson ? '/docs/' : '/';

export default defineConfig({
	site: process.env.URL,
	base,
	trailingSlash: 'always',
	outDir: jetson ? '../dist/jetson-docs' : '../dist/docs',
	// Allow the Mermaid integration's generated HTML in MDX pages.
	markdown: { processor: satteri({ features: { rawHtml: true } }) },
	integrations: [
		mermaid({ autoTheme: true, enableLog: false }),
		starlight({
			title: 'Spot documentation',
			description: "Team 581's Jetson vision system: setup, calibration, and robot integration.",
			favicon: '/favicon.svg',
			social: [
				...(jetson ? [{ icon: 'left-arrow' as const, label: 'Dashboard', href: '/' }] : []),
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/team581/spot-2026' },
			],
			plugins: [team581Theme()],
			sidebar: [
				{ slug: 'index', label: 'Overview' },
				{
					label: 'Getting started',
					items: ['operator/connect', 'operator/name', 'operator/geometry', 'operator/calibrate', 'operator/verify'],
				},
				{
					label: 'Guides',
					items: ['operator/tuning', 'operator/replacement', 'operator/recovery', 'operator/deployment'],
				},
				{
					label: 'Reference',
					items: [
						'operator/java',
						'operator/faults',
						'operator/camera-configuration',
						'operator/vscode-camera-preview',
					],
				},
				{ label: 'Testing', items: ['operator/robot-integration-session'] },
			],
		}),
		mdx(),
	],
});
