import { SpotViewer, angles, cameraAngles } from '@spot/camera-viewer';
import type { PreviewProfile } from '../profile';
interface SavedState {
	selected?: string;
	hidden?: string[];
	orbit?: Partial<SpotViewer['orbit']>;
	drivebase?: Partial<{ visible: boolean; lengthIn: number; widthIn: number }>;
}
declare function acquireVsCodeApi(): {
	getState: () => SavedState | undefined;
	setState: (state: SavedState) => void;
	postMessage: (message: { type: string }) => void;
};
const element = <T extends HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
const vscode = acquireVsCodeApi();
let data: PreviewProfile | undefined,
	selected: string | undefined,
	hidden = new Set<string>();
const saved = vscode.getState();
if (saved) {
	selected = saved.selected;
	hidden = new Set(saved.hidden);
}
let drivebase = { visible: true, lengthIn: 30, widthIn: 30, ...saved?.drivebase };
const canvas = element<HTMLCanvasElement>('canvas');
const viewer = new SpotViewer(canvas, () => ({
	inspection: true,
	mounts: (data?.cameras || []).filter((c) => !hidden.has(c.name)),
	selectedName: selected,
	drivebase: { visible: drivebase.visible, length: drivebase.lengthIn * 0.0254, width: drivebase.widthIn * 0.0254 },
}));
if (saved?.orbit) Object.assign(viewer.orbit, saved.orbit);
function persist() {
	vscode.setState({ selected, hidden: [...hidden], orbit: viewer.orbit, drivebase });
}
function draw() {
	const list = element<HTMLDivElement>('#cameras');
	list.replaceChildren();
	for (const c of data?.cameras || []) {
		const label = document.createElement('label'),
			toggle = document.createElement('input'),
			button = document.createElement('button');
		toggle.type = 'checkbox';
		toggle.checked = !hidden.has(c.name);
		toggle.onchange = () => {
			toggle.checked ? hidden.delete(c.name) : hidden.add(c.name);
			viewer.draw();
			persist();
		};
		button.textContent = c.name;
		button.setAttribute('aria-pressed', String(c.name === selected));
		button.onclick = () => {
			selected = c.name;
			draw();
		};
		label.append(toggle, button);
		list.append(label);
	}
	const c = data?.cameras.find((c) => c.name === selected);
	const fixed = (values: number[]) => values.map((v) => Number(v.toFixed(4))).join(', ');
	const [yaw, pitch, roll] = c ? angles(c.quaternion) : [0, 0, 0];
	element<HTMLHeadingElement>('h2').textContent = data ? `Spot cameras · ${data.robotId}` : 'Spot cameras';
	element<HTMLPreElement>('#details').textContent = c
		? [
				`${c.name} · ${c.required ? 'Required' : 'Optional'}`,
				`Position X, Y, Z (m): ${fixed(c.translation)}`,
				`Java roll, pitch, yaw (°): ${fixed([roll, pitch, yaw])}`,
				`Jetson inspection yaw, pitch, roll (°): ${fixed(cameraAngles(c.quaternion))}`,
				'WPILib pitch: positive = down · negative = up (Java and Jetson)',
				`Quaternion W, X, Y, Z: ${fixed(c.quaternion)}`,
				`Image rotation: ${c.imageRotationDeg}°`,
				...c.capture.map((m) => `Capture request: ${m.width} × ${m.height} · ${m.fps} FPS · ${m.pixelFormat}`),
				'Control policies:',
				...c.controls.map(
					(p) =>
						`  ${p.name}: ${p.value} · ${p.required ? 'required' : 'optional'} · ${p.allowOverride ? 'tunable' : 'pinned'}`,
				),
				...(c.controls.length ? [] : ['  None declared']),
			].join('\n')
		: 'No registered cameras. Add measured camera definitions to CAMERAS in VisionConfig.java.';
	viewer.draw();
	persist();
}
window.addEventListener('message', ({ data: message }: MessageEvent<{ status?: string; data?: PreviewProfile }>) => {
	if (message.status) element<HTMLParagraphElement>('#status').textContent = message.status;
	if (message.data) {
		data = message.data;
		if (!data.cameras.some((c) => c.name === selected)) selected = data.cameras[0]?.name;
		draw();
	}
});
element<HTMLButtonElement>('#refresh').onclick = () => vscode.postMessage({ type: 'refresh' });
element<HTMLButtonElement>('#output').onclick = () => vscode.postMessage({ type: 'output' });
for (const button of document.querySelectorAll<HTMLButtonElement>('[data-view]'))
	button.onclick = () => {
		const view = button.dataset.view;
		if (view === 'reset') viewer.reset();
		else {
			Object.assign(viewer.orbit, {
				azimuth: view === 'side' ? -Math.PI / 2 : 0,
				elevation: view === 'top' ? Math.PI / 2 : 0,
			});
			viewer.draw();
		}
		persist();
	};
for (const event of ['pointerup', 'wheel', 'keydown']) canvas.addEventListener(event, persist);
function syncDrivebase() {
	element<HTMLInputElement>('#drivebase-visible').checked = drivebase.visible;
	element<HTMLInputElement>('#drivebase-length').value = String(drivebase.lengthIn);
	element<HTMLInputElement>('#drivebase-width').value = String(drivebase.widthIn);
	element<HTMLSpanElement>('#drivebase-size').textContent =
		`${drivebase.lengthIn} × ${drivebase.widthIn} in · ${(drivebase.lengthIn * 0.0254).toFixed(3)} × ${(drivebase.widthIn * 0.0254).toFixed(3)} m`;
}
syncDrivebase();
element<HTMLInputElement>('#drivebase-visible').onchange = () => {
	drivebase.visible = element<HTMLInputElement>('#drivebase-visible').checked;
	viewer.draw();
	persist();
};
for (const dimension of ['length', 'width'] as const) {
	const input = element<HTMLInputElement>(`#drivebase-${dimension}`);
	input.oninput = () => {
		const value = input.valueAsNumber;
		const valid = Number.isFinite(value) && value >= 1 && value <= 240;
		input.setAttribute('aria-invalid', String(!valid));
		element<HTMLSpanElement>('#drivebase-error').textContent = document.querySelector(
			'.drivebase-controls [aria-invalid=true]',
		)
			? 'Enter a dimension from 1 to 240 inches. Showing the last valid footprint.'
			: '';
		if (!valid) return;
		drivebase[dimension === 'length' ? 'lengthIn' : 'widthIn'] = value;
		element<HTMLSpanElement>('#drivebase-size').textContent =
			`${drivebase.lengthIn} × ${drivebase.widthIn} in · ${(drivebase.lengthIn * 0.0254).toFixed(3)} × ${(drivebase.widthIn * 0.0254).toFixed(3)} m`;
		viewer.draw();
		persist();
	};
}
vscode.postMessage({ type: 'ready' });
