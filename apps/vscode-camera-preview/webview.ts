interface WebviewAssets {
	cspSource: string;
	nonce: string;
	stylesheet: string;
	script: string;
}
const escapes: Record<string, string> = { '"': '&quot;', '&': '&amp;', '<': '&lt;', '>': '&gt;' };
const attribute = (value: string) => value.replaceAll(/[&"<>]/g, (char: string) => escapes[char]);
export function renderWebview(template: string, assets: WebviewAssets): string {
	return template.replaceAll(/\{\{(cspSource|nonce|stylesheet|script)\}\}/g, (_, key: keyof WebviewAssets) =>
		attribute(assets[key]),
	);
}
