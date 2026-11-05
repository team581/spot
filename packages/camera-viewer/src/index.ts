import * as THREE from 'three';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
export interface Pose {
	translation: number[];
	quaternion: number[];
}
export interface Mount extends Pose {
	name: string;
}
export interface Candidate extends Pose {
	error_px?: number;
}
export interface ViewerState {
	geometry?: Pose | null;
	field?: { length: number; width: number; tags?: (Pose & { id: number; size: number })[] };
	data?: { stale: boolean; candidates?: Candidate[]; tags: { id: number }[] };
	inspection?: boolean;
	mounts?: Mount[];
	selectedName?: string;
	drivebase?: { visible: boolean; length: number; width: number };
}
export function rotate(q: number[], v: number[]): number[] {
	const n = Math.hypot(...q),
		[w, x, y, z] = q.map((a) => a / n),
		[a, b, c] = v;
	return [
		(1 - 2 * (y * y + z * z)) * a + 2 * (x * y - z * w) * b + 2 * (x * z + y * w) * c,
		2 * (x * y + z * w) * a + (1 - 2 * (x * x + z * z)) * b + 2 * (y * z - x * w) * c,
		2 * (x * z - y * w) * a + 2 * (y * z + x * w) * b + (1 - 2 * (x * x + y * y)) * c,
	];
}
export function angles(q: number[]): number[] {
	const n = Math.hypot(...q),
		[w, x, y, z] = q.map((v) => v / n);
	return [
		Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)),
		Math.asin(Math.max(-1, Math.min(1, 2 * (w * y - z * x)))),
		Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)),
	].map((v) => (v * 180) / Math.PI);
}
export function quaternion(yaw: number, pitch: number, roll: number): number[] {
	const [z, y, x] = [yaw, pitch, roll].map((v) => (v * Math.PI) / 360),
		[cz, sz, cy, sy, cx, sx] = [Math.cos(z), Math.sin(z), Math.cos(y), Math.sin(y), Math.cos(x), Math.sin(x)];
	return [
		cz * cy * cx + sz * sy * sx,
		cz * cy * sx - sz * sy * cx,
		cz * sy * cx + sz * cy * sx,
		sz * cy * cx - cz * sy * sx,
	];
}
// Camera controls and stored quaternions both use native WPILib NWU angles.
export function cameraAngles(q: number[]): number[] {
	return angles(q);
}
export function cameraQuaternion(yaw: number, pitch: number, roll: number): number[] {
	return quaternion(yaw, pitch, roll);
}
function multiply(a: number[], b: number[]) {
	const [w, x, y, z] = a,
		[v, i, j, k] = b;
	return [
		w * v - x * i - y * j - z * k,
		w * i + x * v + y * k - z * j,
		w * j - x * k + y * v + z * i,
		w * k + x * j - y * i + z * v,
	];
}
export function robotPose(camera: Pose, mount: Pose): Pose {
	const q = mount.quaternion,
		inverse = [q[0], -q[1], -q[2], -q[3]],
		rotation = multiply(camera.quaternion, inverse),
		offset = rotate(rotation, mount.translation);
	return {
		translation: camera.translation.map((v, i) => v - offset[i]),
		quaternion: rotation,
	};
}
/** CSS custom property (without `--`) that colors a line or label. */
type Color = 'line' | 'blue' | 'accent-text' | 'muted-foreground' | 'good' | 'warning';
export interface Scene {
	/** Lines are named by their color; labels are `CSS2DObject`s. */
	root: THREE.Group;
	center: number[];
	/** Metres to fit in view at zoom 1. */
	extent: number[];
	status: string;
	footer: string;
}
function posed(parent: THREE.Object3D, pose: Pose): THREE.Group {
	const group = new THREE.Group(),
		[w, x, y, z] = pose.quaternion;
	group.position.fromArray(pose.translation);
	group.quaternion.set(x, y, z, w).normalize();
	parent.add(group);
	return group;
}
function lines(parent: THREE.Object3D, geometry: LineSegmentsGeometry, color: Color, width = 1) {
	const object = new LineSegments2(geometry, new LineMaterial({ linewidth: width }));
	object.name = color;
	parent.add(object);
}
const segments = (parent: THREE.Object3D, points: number[][], color: Color, width = 1) =>
	lines(parent, new LineSegmentsGeometry().setPositions(points.flat()), color, width);
const loop = (parent: THREE.Object3D, points: number[][], color: Color, width = 1) =>
	segments(
		parent,
		points.flatMap((p, i) => [p, points[(i + 1) % points.length]]),
		color,
		width,
	);
const rectangle = (x: number, y: number) => [
	[-x / 2, -y / 2, 0],
	[x / 2, -y / 2, 0],
	[x / 2, y / 2, 0],
	[-x / 2, y / 2, 0],
];
function label(parent: THREE.Object3D, text: string, p: number[], color: Color) {
	const element = document.createElement('div');
	element.textContent = text;
	element.style.color = `var(--${color})`;
	element.style.paddingBottom = '8px';
	const object = new CSS2DObject(element);
	object.center.set(0.5, 1);
	object.position.fromArray(p);
	parent.add(object);
}
function box(parent: THREE.Object3D, [x, y, z]: number[], color: Color) {
	const edges = new THREE.EdgesGeometry(new THREE.BoxGeometry(x, y, z).translate(0, 0, z / 2));
	lines(parent, new LineSegmentsGeometry().fromEdgesGeometry(edges), color, 1.5);
}
function arrow(parent: THREE.Object3D, direction: number[], text: string, color: Color) {
	const d = direction.map((v) => v * 0.82),
		sides = direction[0]
			? [
					[d[0], -0.08, d[2]],
					[d[0], 0.08, d[2]],
				]
			: [
					[d[0] - 0.08, d[1], d[2]],
					[d[0] + 0.08, d[1], d[2]],
				];
	segments(parent, [[0, 0, 0], direction, ...sides.flatMap((p) => [direction, p])], color, 2);
	label(parent, text, direction, color);
}
function camera(parent: THREE.Object3D, pose: Pose, color: Color, name: string) {
	const group = posed(parent, pose);
	box(group, [0.18, 0.14, 0.12], color);
	arrow(group, [0.7, 0, 0], 'Lens', color);
	segments(
		group,
		[
			[0, 0, 0.12],
			[0, 0, 0.3],
		],
		color,
		2,
	);
	label(group, name, [0, 0, 0.35], color);
	return group;
}
/** Builds the scene in WPILib NWU metres. Needs `document` for labels but no WebGL. */
export function buildScene({ geometry, field, data, inspection, mounts, selectedName, drivebase }: ViewerState): Scene {
	const root = new THREE.Group(),
		current = data && !data.stale && data.candidates?.length,
		candidates = current ? data!.candidates! : [],
		selected = candidates.reduce<Candidate | null>(
			(a, b) => (!a || (b.error_px ?? NaN) < (a.error_px ?? NaN) ? b : a),
			null,
		),
		world = !inspection && selected && field ? { selected, field } : null;
	if (world) {
		const { length, width } = world.field,
			grid: number[][] = [];
		for (let x = 1; x < length; x++) grid.push([x, 0, 0], [x, width, 0]);
		for (let y = 1; y < width; y++) grid.push([0, y, 0], [length, y, 0]);
		segments(root, grid, 'line');
		loop(
			root,
			rectangle(length, width).map(([x, y]) => [x + length / 2, y + width / 2, 0]),
			'line',
			1.5,
		);
		label(root, 'Blue-wall-right origin', [0, 0, 0], 'blue');
	} else {
		const grid: number[][] = [];
		for (let i = -3; i <= 3; i++)
			grid.push([i * 0.4, -1.2, 0], [i * 0.4, 1.2, 0], [-1.2, i * 0.4, 0], [1.2, i * 0.4, 0]);
		segments(root, grid, 'line');
	}
	const chassis = posed(
		root,
		world && geometry ? robotPose(world.selected, geometry) : { translation: [0, 0, 0], quaternion: [1, 0, 0, 0] },
	);
	if (!mounts) box(chassis, [1, 0.8, 0.15], 'muted-foreground');
	else if (
		drivebase?.visible &&
		Number.isFinite(drivebase.length) &&
		Number.isFinite(drivebase.width) &&
		drivebase.length > 0 &&
		drivebase.width > 0
	)
		// Footprint only: X is length, Y is width. No guessed chassis height.
		loop(chassis, rectangle(drivebase.length, drivebase.width), 'accent-text', 2.5);
	arrow(chassis, [0, 0, 0.8], '+Z up', 'muted-foreground');
	arrow(chassis, [0.95, 0, 0.03], 'Front · +X', 'accent-text');
	arrow(chassis, [0, 0.65, 0.03], '+Y left', 'muted-foreground');
	if (mounts) {
		for (const mount of mounts) {
			const group = camera(root, mount, mount.name === selectedName ? 'blue' : 'muted-foreground', mount.name);
			arrow(group, [0, 0.25, 0], '+Y', 'good');
			arrow(group, [0, 0, 0.25], '+Z', 'accent-text');
		}
	} else if (world) {
		for (const candidate of candidates)
			camera(
				root,
				candidate,
				candidate === selected ? 'blue' : 'warning',
				candidate === selected ? 'Selected camera' : 'Alternate camera',
			);
		const seen = new Set(data!.tags.map((t) => t.id));
		for (const tag of world.field.tags || []) {
			const half = tag.size / 2,
				visible = seen.has(tag.id);
			loop(
				posed(root, tag),
				[
					[0, -half, -half],
					[0, half, -half],
					[0, half, half],
					[0, -half, half],
				],
				visible ? 'good' : 'muted-foreground',
				1.5,
			);
			if (visible) {
				segments(root, [world.selected.translation, tag.translation], 'good');
				label(root, '#' + tag.id, tag.translation, 'good');
			}
		}
	} else if (geometry) camera(root, geometry, 'blue', 'Camera · robot NWU');
	return {
		root,
		center: world ? [world.field.length / 2, world.field.width / 2, 0] : [0, 0, 0.3],
		extent: world ? [world.field.length + 2, world.field.width + 2] : [3, 3],
		status:
			!geometry && !mounts
				? 'Camera geometry unavailable'
				: !mounts && !inspection && !current
					? 'No current field pose · camera mount shown'
					: '',
		footer: mounts ? 'Metres · grid 0.4 m · camera bodies schematic' : 'Drivebase outline is schematic',
	};
}
function dispose(root: THREE.Object3D) {
	root.removeFromParent();
	root.traverse((object) => {
		if (object instanceof CSS2DObject) object.element.remove();
		if (object instanceof LineSegments2) {
			object.geometry.dispose();
			object.material.dispose();
		}
	});
}
const movement = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE']);
const defaultOrbit = () => ({ azimuth: -1.05, elevation: 0.72, zoom: 1, pan: [0, 0, 0] });
export class SpotViewer {
	readonly canvas: HTMLCanvasElement;
	private provider: () => ViewerState;
	/** `pan` offsets the orbit target in WPILib NWU metres. */
	readonly orbit: { azimuth: number; elevation: number; zoom: number; pan: number[] } = defaultOrbit();
	/** Visible height in metres, so movement speed matches what is on screen. */
	private span = 3;
	/** Movement keys held down, by `KeyboardEvent.code`. */
	private held = new Set<string>();
	private frame = 0;
	private last = 0;
	private framing = { center: [0, 0, 0], extent: [3, 3] };
	private drag: number[] | null = null;
	private listeners: (() => void)[] = [];
	private resize: ResizeObserver;
	private renderer: THREE.WebGLRenderer;
	private labels = new CSS2DRenderer();
	private status = document.createElement('div');
	private footer = document.createElement('div');
	private scene = new THREE.Scene();
	private camera = new THREE.OrthographicCamera();
	private content: THREE.Group | null = null;
	private probe = document.createElement('canvas').getContext('2d', { willReadFrequently: true })!;

	constructor(canvas: HTMLCanvasElement, provider: () => ViewerState) {
		this.canvas = canvas;
		this.provider = provider;
		this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
		this.renderer.setPixelRatio(devicePixelRatio);
		const overlay = this.labels.domElement,
			notes = document.createElement('div');
		Object.assign(overlay.style, { position: 'absolute', pointerEvents: 'none', font: '14px system-ui' });
		Object.assign(notes.style, {
			position: 'absolute',
			inset: '16px',
			display: 'flex',
			flexDirection: 'column',
			justifyContent: 'space-between',
			fontSize: '13px',
			color: 'var(--muted-foreground)',
		});
		notes.append(this.status, this.footer);
		overlay.append(notes);
		canvas.after(overlay);
		const on = <K extends keyof HTMLElementEventMap>(
			event: K,
			handler: (event: HTMLElementEventMap[K]) => void,
			options?: AddEventListenerOptions,
		) => {
			canvas.addEventListener(event, handler, options);
			this.listeners.push(() => canvas.removeEventListener(event, handler, options));
		};
		on('pointerdown', (event) => {
			this.drag = [event.clientX, event.clientY];
			canvas.setPointerCapture(event.pointerId);
			canvas.focus();
		});
		on('pointermove', (event) => {
			if (!this.drag) return;
			this.orbit.azimuth -= (event.clientX - this.drag[0]) * 0.008;
			this.orbit.elevation = Math.max(
				0.12,
				Math.min(1.5, this.orbit.elevation + (event.clientY - this.drag[1]) * 0.008),
			);
			this.drag = [event.clientX, event.clientY];
			this.draw();
		});
		for (const event of ['pointerup', 'pointercancel', 'lostpointercapture'] as const)
			on(event, () => {
				this.drag = null;
			});
		on(
			'wheel',
			(event) => {
				event.preventDefault();
				this.orbit.zoom = Math.max(0.25, Math.min(5, this.orbit.zoom * Math.exp(-event.deltaY * 0.001)));
				this.render();
			},
			{ passive: false },
		);
		on('keydown', (event) => {
			if (event.metaKey || event.ctrlKey || event.altKey) return;
			if (movement.has(event.code)) {
				event.preventDefault();
				this.held.add(event.code);
				if (!this.frame) {
					this.last = performance.now();
					this.frame = requestAnimationFrame(this.move);
				}
				return;
			}
			if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-'].includes(event.key)) return;
			event.preventDefault();
			if (event.key === 'ArrowLeft') this.orbit.azimuth -= 0.1;
			if (event.key === 'ArrowRight') this.orbit.azimuth += 0.1;
			if (event.key === 'ArrowUp') this.orbit.elevation = Math.min(1.5, this.orbit.elevation + 0.1);
			if (event.key === 'ArrowDown') this.orbit.elevation = Math.max(0.12, this.orbit.elevation - 0.1);
			if (event.key === '+' || event.key === '=') this.orbit.zoom = Math.min(5, this.orbit.zoom * 1.1);
			if (event.key === '-') this.orbit.zoom = Math.max(0.25, this.orbit.zoom / 1.1);
			this.render();
		});
		on('keyup', (event) => this.held.delete(event.code));
		on('blur', () => this.held.clear());
		this.resize = new ResizeObserver(() => this.render());
		this.resize.observe(canvas);
	}
	reset(): void {
		Object.assign(this.orbit, defaultOrbit());
		this.render();
	}
	/** Moves continuously while WASD/QE are held: A/D pan, Q/E lower/raise, W/S zoom in/out. */
	private move = (time: number) => {
		const seconds = Math.min(0.1, (time - this.last) / 1000),
			held = (code: string) => (this.held.has(code) ? 1 : 0),
			right = (held('KeyD') - held('KeyA')) * this.span * seconds,
			up = (held('KeyE') - held('KeyQ')) * this.span * seconds,
			a = this.orbit.azimuth;
		this.last = time;
		this.orbit.pan = this.orbit.pan.map((v, i) => v + [-Math.sin(a) * right, Math.cos(a) * right, up][i]);
		this.orbit.zoom = Math.max(
			0.25,
			Math.min(5, this.orbit.zoom * Math.exp((held('KeyW') - held('KeyS')) * 1.5 * seconds)),
		);
		this.render();
		this.frame = this.held.size ? requestAnimationFrame(this.move) : 0;
	};
	destroy(): void {
		cancelAnimationFrame(this.frame);
		for (const remove of this.listeners) remove();
		this.resize.disconnect();
		if (this.content) dispose(this.content);
		this.renderer.dispose();
		this.labels.domElement.remove();
	}
	/** Resolves any CSS color (including `oklch()`) to RGB. */
	private color(value: string) {
		this.probe.clearRect(0, 0, 1, 1);
		this.probe.fillStyle = value;
		this.probe.fillRect(0, 0, 1, 1);
		const [r, g, b] = this.probe.getImageData(0, 0, 1, 1).data;
		return new THREE.Color().setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace);
	}
	/** Rebuilds the scene from the provider, then renders. */
	draw(): void {
		if (this.content) dispose(this.content);
		const { root, center, extent, status, footer } = buildScene(this.provider()),
			styles = getComputedStyle(this.canvas),
			palette = new Map<string, THREE.Color>();
		this.content = root;
		this.scene.add(root);
		root.traverse((object) => {
			if (!(object instanceof LineSegments2)) return;
			if (!palette.has(object.name))
				palette.set(object.name, this.color(styles.getPropertyValue(`--${object.name}`).trim()));
			object.material.color.copy(palette.get(object.name)!);
		});
		this.status.textContent = status;
		this.footer.textContent = footer;
		this.framing = { center, extent };
		this.render();
	}
	/** Renders the current scene from the current orbit. */
	private render(): void {
		const { canvas, camera, labels } = this,
			{ center, extent } = this.framing,
			width = canvas.clientWidth,
			height = canvas.clientHeight;
		if (!width || !height) return;
		this.renderer.setSize(width, height, false);
		labels.setSize(width, height);
		Object.assign(labels.domElement.style, { left: `${canvas.offsetLeft}px`, top: `${canvas.offsetTop}px` });
		// Orthographic view of the orbit; the target sits slightly below the middle like a turntable.
		const { azimuth: a, elevation: e, zoom, pan } = this.orbit,
			metres = 1 / Math.min(width / extent[0], height / extent[1]),
			target = new THREE.Vector3().fromArray(center.map((v, i) => v + (pan[i] ?? 0)));
		this.span = (height * metres) / zoom;
		Object.assign(camera, {
			left: (-width / 2) * metres,
			right: (width / 2) * metres,
			top: height * 0.56 * metres,
			bottom: -height * 0.44 * metres,
			near: 0,
			far: 200,
			zoom,
		});
		camera.position
			.set(Math.cos(e) * Math.cos(a), Math.cos(e) * Math.sin(a), Math.sin(e))
			.multiplyScalar(100)
			.add(target);
		camera.up.set(-Math.sin(e) * Math.cos(a), -Math.sin(e) * Math.sin(a), Math.cos(e));
		camera.lookAt(target);
		camera.updateProjectionMatrix();
		this.renderer.render(this.scene, camera);
		labels.render(this.scene, camera);
	}
}
