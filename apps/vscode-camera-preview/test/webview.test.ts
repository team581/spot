import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { renderWebview } from '../webview.ts';

void test('webview template keeps nonce-based CSP and escapes asset attributes', () => {
	const template = readFileSync(new URL('../media/preview.html', import.meta.url), 'utf8');
	const html = renderWebview(template, {
		cspSource: 'https://vscode-resource.test',
		nonce: 'nonce-value',
		script: 'https://vscode-resource.test/preview".js',
		stylesheet: 'https://vscode-resource.test/style?x=1&y=2',
	});
	assert.match(html, /script-src 'nonce-nonce-value'/);
	assert.match(html, /nonce="nonce-value"/);
	assert.match(html, /style\?x=1&amp;y=2/);
	assert.match(html, /preview&quot;\.js/);
	assert.doesNotMatch(html, /\{\{/);
});
