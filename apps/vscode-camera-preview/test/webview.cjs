const test = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { parseProfile } = require('../profile.ts');
const { renderWebview } = require('../webview.ts');

void test('profile export rejects unsupported schema versions and absent camera inventories', () => {
	assert.throws(() => parseProfile('{"schemaVersion":2,"cameras":[]}'), /Unsupported preview format/);
	assert.throws(() => parseProfile('{"schemaVersion":1}'), /Unsupported preview format/);
	assert.deepEqual(parseProfile('{"schemaVersion":1,"robotId":"test","cameras":[]}').cameras, []);
});
void test('webview template keeps nonce-based CSP and escapes asset attributes', () => {
	const template = readFileSync(require.resolve('../media/preview.html'), 'utf8');
	const html = renderWebview(template, {
		cspSource: 'https://vscode-resource.test',
		nonce: 'nonce-value',
		stylesheet: 'https://vscode-resource.test/style?x=1&y=2',
		script: 'https://vscode-resource.test/preview".js',
	});
	assert.match(html, /script-src 'nonce-nonce-value'/);
	assert.match(html, /nonce="nonce-value"/);
	assert.match(html, /style\?x=1&amp;y=2/);
	assert.match(html, /preview&quot;\.js/);
	assert.doesNotMatch(html, /\{\{/);
});
