import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { parse } from 'parse5';
import type { DefaultTreeAdapterMap } from 'parse5';

type Element = DefaultTreeAdapterMap['element'];
type Node = DefaultTreeAdapterMap['node'];

function* elements(node: Node): Generator<Element> {
	if ('tagName' in node) {
		yield node;
	}
	if ('childNodes' in node) {
		for (const child of node.childNodes) {
			yield* elements(child);
		}
	}
}

function textContent(node: Node): string {
	if ('value' in node) {
		return node.value;
	}
	return 'childNodes' in node ? node.childNodes.map(textContent).join('') : '';
}

await Promise.all(
	(
		[
			['docs', '/'],
			['jetson-docs', '/docs/'],
		] as const
	).map(async ([target, base]) => {
		const output = fileURLToPath(new URL(`../../../dist/${target}/`, import.meta.url));
		const documents = new Map<string, Element[]>();
		for (const file of readdirSync(output, { encoding: 'utf8', recursive: true })) {
			if (file.endsWith('.html')) {
				documents.set(file, [...elements(parse(readFileSync(join(output, file), 'utf8')))]);
			}
		}

		if (base === '/docs/') {
			await test('Jetson docs provide a link back to the dashboard root', () => {
				const links = documents.get('index.html')!.filter((node) => node.tagName === 'a');
				assert.ok(
					links.some(
						(node) =>
							textContent(node).trim() === 'Dashboard' &&
							node.attrs.some(({ name, value }) => name === 'href' && value === '/'),
					),
				);
			});
		}

		await test(`${target}: generated links, section anchors, scripts, and styles resolve`, () => {
			assert.ok(documents.has('index.html'), 'Missing site homepage');
			for (const [file, nodes] of documents) {
				for (const node of nodes) {
					for (const attr of node.attrs.filter(({ name }) => name === 'href' || name === 'src')) {
						const destination = new URL(attr.value, `https://docs.test${base}${file.replace(/index\.html$/, '')}`);
						if (destination.origin !== 'https://docs.test') {
							continue;
						}
						if (base === '/docs/' && node.tagName === 'a' && attr.value === '/') {
							continue;
						}
						assert.ok(destination.pathname.startsWith(base), `Link escapes docs base: ${attr.value} in ${file}`);
						const path = decodeURIComponent(destination.pathname).slice(base.length);
						const targetFile = destination.pathname.endsWith('/') ? `${path}index.html` : path;
						assert.ok(existsSync(join(output, targetFile)), `Missing ${attr.value} in ${file}`);
						if (destination.hash && documents.has(targetFile)) {
							const id = decodeURIComponent(destination.hash.slice(1));
							assert.ok(
								documents
									.get(targetFile)!
									.some((element) => element.attrs.some(({ name, value }) => name === 'id' && value === id)),
								`Missing anchor ${attr.value} in ${file}`,
							);
						}
					}
				}
			}
		});
	}),
);
