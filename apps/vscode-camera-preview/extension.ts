import * as vscode from 'vscode';
import * as path from 'node:path';
import { promises as fs, readFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { discover } from './project';
import { parseConfig, type SpotConfig } from './profile';
import { renderWebview } from './webview';
export function activate(context: vscode.ExtensionContext) {
	const panels = new Map<string, vscode.WebviewPanel>();
	const suppressed = new Set<string>();
	async function open(uri?: vscode.Uri, automatic = false) {
		uri ??= vscode.window.activeTextEditor?.document.uri;
		if (
			!uri ||
			uri.scheme !== 'file' ||
			!['VisionConfig.java', 'spot-config.json'].includes(path.basename(uri.fsPath)) ||
			!vscode.workspace.isTrusted
		)
			return;
		const key = uri.fsPath;
		if (automatic && suppressed.has(key)) return;
		if (panels.has(key)) {
			if (!automatic) panels.get(key)!.reveal(vscode.ViewColumn.Beside, true);
			return;
		}
		let config: string;
		try {
			config = discover(key);
		} catch (e) {
			if (!automatic) vscode.window.showErrorMessage(String(e));
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
		panels.set(key, panel);
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
			latest: SpotConfig | undefined;
		const status = (text: string) => panel.webview.postMessage({ status: text });
		async function load() {
			try {
				latest = parseConfig(await fs.readFile(config, 'utf8'));
				if (!disposed) panel.webview.postMessage({ data: latest, status: 'Current · saved spot-config.json' });
			} catch (e) {
				if (!disposed) status(`${latest ? 'Stale preview' : 'Cannot read spot-config.json'} · ${String(e)}`);
			}
		}
		const watcher = vscode.workspace.createFileSystemWatcher(
			new vscode.RelativePattern(path.dirname(config), path.basename(config)),
		);
		const subscriptions = [
			watcher,
			watcher.onDidChange(load),
			watcher.onDidCreate(load),
			watcher.onDidDelete(load),
			vscode.workspace.onDidChangeTextDocument((e) => {
				if (e.document.uri.fsPath === config && e.document.isDirty)
					status('Unsaved changes · showing saved spot-config.json');
			}),
			panel.webview.onDidReceiveMessage((message: { type?: string }) => {
				if (message.type === 'ready' && latest) panel.webview.postMessage({ data: latest });
				else if (message.type === 'ready' || message.type === 'refresh') void load();
			}),
		];
		panel.onDidDispose(() => {
			disposed = true;
			subscriptions.forEach((s) => s.dispose());
			panels.delete(key);
			suppressed.add(key);
		});
	}
	context.subscriptions.push(vscode.commands.registerCommand('spot.previewCameras', (uri?: vscode.Uri) => open(uri)));
	const auto = (editor?: vscode.TextEditor) => {
		if (editor && vscode.workspace.getConfiguration().get('spot.cameraPreview.autoOpen', true))
			void open(editor.document.uri, true);
	};
	context.subscriptions.push(vscode.window.onDidChangeActiveTextEditor(auto));
	auto(vscode.window.activeTextEditor);
}
