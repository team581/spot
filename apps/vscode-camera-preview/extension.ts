import * as vscode from 'vscode';
import * as path from 'node:path';
import { promises as fs, readFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { parseConfig, type PreviewCamera } from './config';
import { renderWebview } from './webview';

const configName = 'spot.toml';

export function activate(context: vscode.ExtensionContext) {
	const panels = new Map<string, vscode.WebviewPanel>();
	const suppressed = new Set<string>();
	function open(uri?: vscode.Uri, automatic = false) {
		uri ??= vscode.window.activeTextEditor?.document.uri;
		if (!uri || uri.scheme !== 'file' || path.basename(uri.fsPath) !== configName || !vscode.workspace.isTrusted)
			return;
		const config = uri.fsPath;
		if (automatic && suppressed.has(config)) return;
		if (panels.has(config)) {
			if (!automatic) panels.get(config)!.reveal(vscode.ViewColumn.Beside, true);
			return;
		}
		const panel = vscode.window.createWebviewPanel(
			'spotCameraPreview',
			'Spot Cameras',
			{ viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
			{
				enableScripts: true,
				localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')],
			},
		);
		panels.set(config, panel);
		const nonce = randomBytes(16).toString('hex');
		const asset = (name: string) =>
			panel.webview.asWebviewUri(vscode.Uri.joinPath(context.extensionUri, 'media', name)).toString();
		panel.webview.html = renderWebview(readFileSync(path.join(context.extensionPath, 'media/preview.html'), 'utf8'), {
			cspSource: panel.webview.cspSource,
			nonce,
			stylesheet: asset('preview.css'),
			script: asset('preview.bundle.js'),
		});
		let disposed = false,
			latest: PreviewCamera[] | undefined;
		const status = (text: string) => !disposed && void panel.webview.postMessage({ status: text });
		async function load() {
			try {
				latest = parseConfig(await fs.readFile(config, 'utf8'));
				const dirty = vscode.workspace.textDocuments.some((d) => d.uri.fsPath === config && d.isDirty);
				if (!disposed)
					void panel.webview.postMessage({
						cameras: latest,
						status: dirty ? `Unsaved changes · showing saved ${configName}` : `Current · saved ${configName}`,
					});
			} catch (e) {
				status(
					`${latest ? 'Showing last valid preview' : `Cannot preview ${configName}`} · ${e instanceof Error ? e.message : String(e)}`,
				);
			}
		}
		const watcher = vscode.workspace.createFileSystemWatcher(
			new vscode.RelativePattern(path.dirname(config), configName),
		);
		const subscriptions = [
			watcher,
			watcher.onDidChange(load),
			watcher.onDidCreate(load),
			watcher.onDidDelete(load),
			vscode.workspace.onDidChangeTextDocument(({ document }) => {
				if (document.uri.fsPath !== config) return;
				// Saving reloads through the watcher; reverting needs a reload to clear the unsaved status.
				if (document.isDirty) status(`Unsaved changes · showing saved ${configName}`);
				else void load();
			}),
			panel.webview.onDidReceiveMessage((message: { type?: string }) => {
				if (message.type === 'ready' || message.type === 'refresh') void load();
			}),
		];
		panel.onDidDispose(() => {
			disposed = true;
			subscriptions.forEach((s) => s.dispose());
			panels.delete(config);
			suppressed.add(config);
		});
	}
	context.subscriptions.push(vscode.commands.registerCommand('spot.previewCameras', (uri?: vscode.Uri) => open(uri)));
	const auto = (editor?: vscode.TextEditor) => {
		if (editor && vscode.workspace.getConfiguration().get('spot.cameraPreview.autoOpen', true))
			open(editor.document.uri, true);
	};
	context.subscriptions.push(vscode.window.onDidChangeActiveTextEditor(auto));
	auto(vscode.window.activeTextEditor);
}
