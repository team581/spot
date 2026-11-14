import { SpotViewer } from '@spot/camera-viewer';
import type { PreviewCamera } from '../config';
import { previewMount } from './cameras';

interface Drivebase {
	visible: boolean;
	lengthIn: number;
	widthIn: number;
}
interface SavedState {
	selected?: string;
	hidden?: string[];
	orbit?: Partial<SpotViewer['orbit']>;
	drivebase?: Partial<Drivebase>;
}
declare function acquireVsCodeApi(): {
	getState: () => SavedState | undefined;
	setState: (state: SavedState) => void;
	postMessage: (message: { type: string }) => void;
};
const element = (selector: string) => document.querySelector<HTMLElement>(selector)!;
const vscode = acquireVsCodeApi();
const saved = vscode.getState();
let cameras: PreviewCamera[] | undefined;
let selected = saved?.selected;
const hidden = new Set(saved?.hidden);
const drivebase: Drivebase = { lengthIn: 30, visible: true, widthIn: 30, ...saved?.drivebase };
const canvas = document.querySelector('canvas')!;
const viewer = new SpotViewer(canvas, () => ({
	drivebase: { length: drivebase.lengthIn * 0.0254, visible: drivebase.visible, width: drivebase.widthIn * 0.0254 },
	inspection: true,
	mounts: (cameras ?? []).filter((c) => !hidden.has(c.name)).map(previewMount),
	selectedName: selected,
}));
if (saved?.orbit) {
	Object.assign(viewer.orbit, saved.orbit);
}
function persist() {
	vscode.setState({ drivebase, hidden: [...hidden], orbit: viewer.orbit, selected });
}
function details(c: PreviewCamera): [string, string, boolean?][] {
	const { x, y, z, roll, pitch, yaw } = c.mount;
	const controls = Object.entries(c.controls).map(([name, value]) => `${name} = ${value}`);
	const device = [c.serial && `serial ${c.serial}`, c.port && `port ${c.port}`].filter(Boolean);
	return [
		['Name', c.name],
		['Required', c.required ? 'Yes' : 'No'],
		['Device', device.join(', ') || 'Not set'],
		['Mode', c.mode],
		['Position X, Y, Z (m)', [x, y, z].join(', ')],
		['Roll, pitch, yaw (°)', [roll, pitch, yaw].join(', ')],
		['Controls', controls.join(', ') || 'Camera defaults'],
		c.calibrations.includes(c.resolution)
			? ['Calibrations', c.calibrations.join(', ')]
			: [
					'Calibrations',
					`${c.calibrations.length > 0 ? c.calibrations.join(', ') : 'None'} · none for mode resolution ${c.resolution}`,
					true,
				],
	];
}
function draw() {
	const list = element('#cameras');
	list.replaceChildren();
	for (const c of cameras ?? []) {
		const label = document.createElement('label');
		const toggle = document.createElement('input');
		const button = document.createElement('button');
		toggle.type = 'checkbox';
		toggle.checked = !hidden.has(c.name);
		toggle.title = 'Show in preview';
		toggle.addEventListener('change', () => {
			toggle.checked ? hidden.delete(c.name) : hidden.add(c.name);
			viewer.draw();
			persist();
		});
		button.textContent = c.name;
		button.setAttribute('aria-pressed', String(c.name === selected));
		button.addEventListener('click', () => {
			selected = c.name;
			draw();
		});
		label.append(toggle, button);
		list.append(label);
	}
	const camera = cameras?.find((c) => c.name === selected);
	const rows = camera
		? details(camera).flatMap(([term, value, warning]) => {
				const dt = document.createElement('dt');
				const dd = document.createElement('dd');
				dt.textContent = term;
				dd.textContent = value;
				dd.classList.toggle('warning', Boolean(warning));
				return [dt, dd];
			})
		: [];
	element('#details').replaceChildren(...rows);
	if (cameras && cameras.length === 0) {
		element('#details').textContent = 'No cameras. Add a [cameras.<name>] table to spot.toml.';
	}
	viewer.draw();
	persist();
}
window.addEventListener('message', ({ data }: MessageEvent<{ status?: string; cameras?: PreviewCamera[] }>) => {
	const { status, cameras: received } = data;
	if (status) {
		element('#status').textContent = status;
	}
	if (received) {
		cameras = received;
		if (!cameras.some((c) => c.name === selected)) {
			selected = cameras[0]?.name;
		}
		draw();
	}
});
element('#refresh').addEventListener('click', () => {
	vscode.postMessage({ type: 'refresh' });
});
for (const button of document.querySelectorAll<HTMLButtonElement>('[data-view]')) {
	button.addEventListener('click', () => {
		const { view } = button.dataset;
		if (view === 'reset') {
			viewer.reset();
		} else {
			Object.assign(viewer.orbit, {
				azimuth: view === 'side' ? -Math.PI / 2 : 0,
				elevation: view === 'top' ? Math.PI / 2 : 0,
			});
			viewer.draw();
		}
		persist();
	});
}
for (const event of ['pointerup', 'wheel', 'keydown', 'keyup']) {
	canvas.addEventListener(event, persist);
}
const size = () =>
	(element('#drivebase-size').textContent =
		`${drivebase.lengthIn} × ${drivebase.widthIn} in · ${(drivebase.lengthIn * 0.0254).toFixed(3)} × ${(drivebase.widthIn * 0.0254).toFixed(3)} m`);
const visible = document.querySelector<HTMLInputElement>('#drivebase-visible')!;
visible.checked = drivebase.visible;
visible.addEventListener('change', () => {
	drivebase.visible = visible.checked;
	viewer.draw();
	persist();
});
for (const dimension of ['length', 'width'] as const) {
	const input = document.querySelector<HTMLInputElement>(`#drivebase-${dimension}`)!;
	const key = dimension === 'length' ? 'lengthIn' : 'widthIn';
	input.value = String(drivebase[key]);
	input.addEventListener('input', () => {
		const value = input.valueAsNumber;
		const valid = Number.isFinite(value) && value >= 1 && value <= 240;
		input.setAttribute('aria-invalid', String(!valid));
		element('#drivebase-error').textContent = document.querySelector('.drivebase-controls [aria-invalid=true]')
			? 'Enter a dimension from 1 to 240 inches. Showing the last valid footprint.'
			: '';
		if (!valid) {
			return;
		}
		drivebase[key] = value;
		size();
		viewer.draw();
		persist();
	});
}
size();
vscode.postMessage({ type: 'ready' });
