import * as vscode from 'vscode';
import * as path from 'node:path';
import { promises as fs, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { discover } from './project';
import { parseProfile, type PreviewProfile } from './profile';
import { renderWebview } from './webview';
export function activate(context: vscode.ExtensionContext) {
	const output = vscode.window.createOutputChannel('Spot Camera Preview');
	const panels = new Map<string, vscode.WebviewPanel>();
	const suppressed = new Set<string>();
	context.subscriptions.push(output);
	async function open(uri?: vscode.Uri, automatic = false) {
		uri ??= vscode.window.activeTextEditor?.document.uri;
		if (
			!uri ||
			uri.scheme !== 'file' ||
			path.basename(uri.fsPath) !== 'VisionConfig.java' ||
			!vscode.workspace.isTrusted
		)
			return;
		const key = uri.fsPath;
		if (automatic && suppressed.has(key)) return;
		if (panels.has(key)) {
			if (!automatic) panels.get(key)!.reveal(vscode.ViewColumn.Beside, true);
			return;
		}
		let project: ReturnType<typeof discover>;
		try {
			project = discover(key);
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
			running = false,
			generation = 0,
			timer: NodeJS.Timeout | undefined,
			child: ReturnType<typeof spawn> | undefined;
		let latest: PreviewProfile | undefined;
		const dirty = () =>
			vscode.workspace.textDocuments.some((d) => d.isDirty && d.uri.fsPath.startsWith(project.root + path.sep));
		const status = (text: string) => panel.webview.postMessage({ status: text });
		async function run() {
			if (disposed || running) return;
			running = true;
			const current = generation;
			status('Building saved configuration…');
			try {
				const wrapper = path.join(project.root, process.platform === 'win32' ? 'gradlew.bat' : 'gradlew');
				output.appendLine(`Exporting ${key}`);
				await new Promise<void>((resolve, reject) => {
					child = spawn(wrapper, [project.task, '--console=plain'], {
						cwd: project.root,
						shell: process.platform === 'win32',
					});
					child.stdout?.on('data', (data) => output.append(data.toString()));
					child.stderr?.on('data', (data) => output.append(data.toString()));
					child.once('error', reject);
					child.once('exit', (code) => (code === 0 ? resolve() : reject(Error(`Gradle exited ${code}`))));
				});
				const data = parseProfile(
					await fs.readFile(path.join(project.project, 'build/spot-camera-preview/profile.json'), 'utf8'),
				);
				if (!disposed && current === generation) {
					latest = data;
					panel.webview.postMessage({
						data,
						status: dirty() ? 'Unsaved changes · showing saved configuration' : 'Current · saved configuration',
					});
				}
			} catch (e) {
				if (!disposed && current === generation)
					status(`${latest ? 'Stale preview' : 'Export failed'} · ${String(e)} · see Build output`);
			} finally {
				running = false;
				child = undefined;
				if (!disposed && current !== generation) void run();
			}
		}
		const schedule = () => {
			generation++;
			clearTimeout(timer);
			timer = setTimeout(() => void run(), 400);
		};
		const watcher = vscode.workspace.createFileSystemWatcher(
			new vscode.RelativePattern(project.root, '**/*.{java,gradle}'),
		);
		const changed = (u: vscode.Uri) => {
			if (!u.fsPath.includes(`${path.sep}build${path.sep}`)) schedule();
		};
		const subscriptions = [
			watcher,
			watcher.onDidChange(changed),
			watcher.onDidCreate(changed),
			watcher.onDidDelete(changed),
			vscode.workspace.onDidChangeTextDocument((e) => {
				if (e.document.uri.fsPath.startsWith(project.root + path.sep) && e.document.isDirty)
					status('Unsaved changes · showing last exported configuration');
			}),
			panel.webview.onDidReceiveMessage((message: { type?: string }) => {
				if (message.type === 'ready') {
					if (latest) panel.webview.postMessage({ data: latest });
					else schedule();
				}
				if (message.type === 'refresh') schedule();
				if (message.type === 'output') output.show(true);
			}),
		];
		panel.onDidDispose(() => {
			disposed = true;
			clearTimeout(timer);
			child?.kill();
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
