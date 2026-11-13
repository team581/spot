import * as THREE from 'three';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';

export interface Pose {
	position: THREE.Vector3;
	quaternion: THREE.Quaternion;
}
export interface Mount extends Pose {
	name: string;
}
/** A camera on the field: its robot-to-camera mount, plus what it currently sees. */
export interface FieldCamera extends Mount {
	/** Any CSS color, used for this camera's robot, body, and tag lines. */
	color: string;
	/** The robot's field pose estimated from this camera, or null without one. */
	robot: Pose | null;
	/** IDs of the tags the estimate used. */
	tags: number[];
}
export interface ViewerState {
	field?: { length: number; width: number; tags?: (Pose & { id: number; size: number })[] };
	/** Shown on `field`: each camera's robot estimate, mount, and the tags it used. */
	cameras?: FieldCamera[];
	inspection?: boolean;
	mounts?: Mount[];
	selectedName?: string;
	drivebase?: { visible: boolean; length: number; width: number };
}
/** A CSS custom property name (without `--`), or any other CSS color. */
type Color = 'line' | 'blue' | 'accent-text' | 'muted-foreground' | 'good' | 'warning' | (string & {});
const isProperty = (color: string) => /^[\w-]+$/.test(color);
export interface Scene {
	/** Lines are named by their color; labels are `CSS2DObject`s. */
	root: THREE.Group;
	center: number[];
	/** Metres to fit in view at zoom 1. */
	extent: number[];
	/** Framed close on the robot's field pose; the viewer then holds this framing until reset. */
	focused: boolean;
	status: string;
}
function posed(parent: THREE.Object3D, pose: Pose): THREE.Group {
	const group = new THREE.Group();
	group.position.copy(pose.position);
	group.quaternion.copy(pose.quaternion);
	parent.add(group);
	return group;
}
function lines(parent: THREE.Object3D, geometry: LineSegmentsGeometry, color: Color, width = 1) {
	const object = new LineSegments2(geometry, new LineMaterial({ linewidth: width }));
	object.name = color;
	parent.add(object);
}
const segments = (parent: THREE.Object3D, points: number[][], color: Color, width = 1) => {
	lines(parent, new LineSegmentsGeometry().setPositions(points.flat()), color, width);
};
const loop = (parent: THREE.Object3D, points: number[][], color: Color, width = 1) => {
	segments(
		parent,
		points.flatMap((p, i) => [p, points[(i + 1) % points.length]]),
		color,
		width,
	);
};
const rectangle = (x: number, y: number) => [
	[-x / 2, -y / 2, 0],
	[x / 2, -y / 2, 0],
	[x / 2, y / 2, 0],
	[-x / 2, y / 2, 0],
];
function label(parent: THREE.Object3D, text: string, p: number[], color: Color) {
	const element = document.createElement('div');
	element.textContent = text;
	element.style.color = isProperty(color) ? `var(--${color})` : color;
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
	const d = direction.map((v) => v * 0.82);
	const sides = direction[0]
		? [
				[d[0], -0.08, d[2]],
				[d[0], 0.08, d[2]],
			]
		: [
				[d[0] - 0.08, d[1], d[2]],
				[d[0] + 0.08, d[1], d[2]],
			];
	segments(parent, [[0, 0, 0], direction, ...sides.flatMap((p) => [direction, p])], color, 2);
	if (text) {
		label(parent, text, direction, color);
	}
}
function camera(parent: THREE.Object3D, pose: Pose, color: Color, name: string, lens = 'Lens') {
	const group = posed(parent, pose);
	box(group, [0.18, 0.14, 0.12], color);
	arrow(group, [0.7, 0, 0], lens, color);
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
export function buildScene({ field, cameras, inspection, mounts, selectedName, drivebase }: ViewerState): Scene {
	const root = new THREE.Group();
	const arena = !inspection && !mounts ? field : undefined;
	const estimates = arena ? (cameras ?? []).filter((c) => c.robot) : [];
	// Cameras without an estimate ride on another camera's robot, or one at midfield.
	const reference: Pose = estimates[0]?.robot ?? {
		quaternion: new THREE.Quaternion(),
		position: arena ? new THREE.Vector3(arena.length / 2, arena.width / 2, 0) : new THREE.Vector3(),
	};
	if (arena) {
		const { length, width } = arena;
		const grid: number[][] = [];
		for (let x = 1; x < length; x++) {
			grid.push([x, 0, 0], [x, width, 0]);
		}
		for (let y = 1; y < width; y++) {
			grid.push([0, y, 0], [length, y, 0]);
		}
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
		for (let i = -3; i <= 3; i++) {
			grid.push([i * 0.4, -1.2, 0], [i * 0.4, 1.2, 0], [-1.2, i * 0.4, 0], [1.2, i * 0.4, 0]);
		}
		segments(root, grid, 'line');
		const chassis = posed(root, reference);
		if (
			drivebase?.visible &&
			Number.isFinite(drivebase.length) &&
			Number.isFinite(drivebase.width) &&
			drivebase.length > 0 &&
			drivebase.width > 0
		)
		// Footprint only: X is length, Y is width. No guessed chassis height.
		{
			loop(chassis, rectangle(drivebase.length, drivebase.width), 'accent-text', 2.5);
		}
		arrow(chassis, [0, 0, 0.8], '+Z up', 'muted-foreground');
		arrow(chassis, [0.95, 0, 0.03], 'Front · +X', 'accent-text');
		arrow(chassis, [0, 0.65, 0.03], '+Y left', 'muted-foreground');
	}
	if (mounts) {
		for (const mount of mounts) {
			const group = camera(root, mount, mount.name === selectedName ? 'blue' : 'muted-foreground', mount.name);
			arrow(group, [0, 0.25, 0], '+Y', 'good');
			arrow(group, [0, 0, 0.25], '+Z', 'accent-text');
		}
	} else if (arena) {
		const robot = (chassis: THREE.Object3D, color: Color) => {
			box(chassis, [0.9, 0.9, 0.15], color);
			arrow(chassis, [0.75, 0, 0.15], '', color);
		};
		const tags = new Map((arena.tags ?? []).map((t) => [t.id, t]));
		const seen = new Map<number, Color>();
		if (estimates.length === 0) {
			robot(posed(root, reference), 'muted-foreground');
		}
		for (const c of cameras ?? []) {
			const chassis = posed(root, c.robot ?? reference);
			if (c.robot) {
				robot(chassis, c.color);
			}
			const body = camera(chassis, c, c.color, c.name, '');
			const position = body.getWorldPosition(new THREE.Vector3());
			for (const id of c.robot ? c.tags : []) {
				const tag = tags.get(id);
				if (!tag) {
					continue;
				}
				segments(root, [position.toArray(), tag.position.toArray()], c.color);
				if (!seen.has(id)) {
					seen.set(id, c.color);
				}
			}
		}
		for (const tag of tags.values()) {
			const half = tag.size / 2;
			const color = seen.get(tag.id) ?? 'muted-foreground';
			loop(
				posed(root, tag),
				[
					[0, -half, -half],
					[0, half, -half],
					[0, half, half],
					[0, -half, half],
				],
				color,
				1.5,
			);
			label(root, `#${tag.id}`, tag.position.toArray(), color);
		}
	}
	return {
		center:
			estimates.length > 0
				? [reference.position.x, reference.position.y, 0.3]
				: arena
					? [arena.length / 2, arena.width / 2, 0]
					: [0, 0, 0.3],
		extent: arena && estimates.length === 0 ? [arena.length + 2, arena.width + 2] : [3, 3],
		focused: estimates.length > 0,
		root,
		status: arena && estimates.length === 0 ? 'No camera sees a tag · mounts shown on a robot at midfield' : '',
	};
}
function dispose(root: THREE.Object3D) {
	root.removeFromParent();
	root.traverse((object) => {
		if (object instanceof CSS2DObject) {
			object.element.remove();
		}
		if (object instanceof LineSegments2) {
			object.geometry.dispose();
			object.material.dispose();
		}
	});
}
const movement = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE']);
const defaultOrbit = () => ({ azimuth: -1.05, elevation: 0.72, pan: [0, 0, 0], zoom: 1 });
export class SpotViewer {
	readonly canvas: HTMLCanvasElement;
	private readonly provider: () => ViewerState;
	/** `pan` offsets the orbit target in WPILib NWU metres. */
	readonly orbit: { azimuth: number; elevation: number; zoom: number; pan: number[] } = defaultOrbit();
	/** Visible height in metres, so movement speed matches what is on screen. */
	private span = 3;
	/** Movement keys held down, by `KeyboardEvent.code`. */
	private readonly held = new Set<string>();
	private frame = 0;
	private last = 0;
	private framing = { center: [0, 0, 0], extent: [3, 3] };
	/** Holds framing on the robot so flickering detections don't move the view. */
	private focused = false;
	private drag: number[] | null = null;
	private readonly listeners: (() => void)[] = [];
	private readonly resize: ResizeObserver;
	private readonly renderer: THREE.WebGLRenderer;
	private readonly labels = new CSS2DRenderer();
	private readonly status = document.createElement('div');
	private readonly scene = new THREE.Scene();
	private readonly camera = new THREE.OrthographicCamera();
	private content: THREE.Group | null = null;
	private readonly probe = document.createElement('canvas').getContext('2d', { willReadFrequently: true })!;

	constructor(canvas: HTMLCanvasElement, provider: () => ViewerState) {
		this.canvas = canvas;
		this.provider = provider;
		this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, canvas });
		this.renderer.setPixelRatio(devicePixelRatio);
		const overlay = this.labels.domElement;
		Object.assign(overlay.style, { font: '14px system-ui', pointerEvents: 'none', position: 'absolute' });
		Object.assign(this.status.style, {
			color: 'var(--muted-foreground)',
			fontSize: '13px',
			left: '16px',
			position: 'absolute',
			top: '16px',
		});
		overlay.append(this.status);
		canvas.after(overlay);
		const on = <K extends keyof HTMLElementEventMap>(
			event: K,
			handler: (event: HTMLElementEventMap[K]) => void,
			options?: AddEventListenerOptions,
		) => {
			canvas.addEventListener(event, handler, options);
			this.listeners.push(() => {
				canvas.removeEventListener(event, handler, options);
			});
		};
		on('pointerdown', (event) => {
			this.drag = [event.clientX, event.clientY];
			canvas.setPointerCapture(event.pointerId);
			canvas.focus();
		});
		on('pointermove', (event) => {
			if (!this.drag) {
				return;
			}
			this.orbit.azimuth -= (event.clientX - this.drag[0]) * 0.008;
			this.orbit.elevation = Math.max(
				0.12,
				Math.min(1.5, this.orbit.elevation + (event.clientY - this.drag[1]) * 0.008),
			);
			this.drag = [event.clientX, event.clientY];
			this.draw();
		});
		for (const event of ['pointerup', 'pointercancel', 'lostpointercapture'] as const) {
			on(event, () => {
				this.drag = null;
			});
		}
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
			if (event.metaKey || event.ctrlKey || event.altKey) {
				return;
			}
			if (movement.has(event.code)) {
				event.preventDefault();
				this.held.add(event.code);
				if (!this.frame) {
					this.last = performance.now();
					this.frame = requestAnimationFrame(this.move);
				}
				return;
			}
			if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-'].includes(event.key)) {
				return;
			}
			event.preventDefault();
			if (event.key === 'ArrowLeft') {
				this.orbit.azimuth -= 0.1;
			}
			if (event.key === 'ArrowRight') {
				this.orbit.azimuth += 0.1;
			}
			if (event.key === 'ArrowUp') {
				this.orbit.elevation = Math.min(1.5, this.orbit.elevation + 0.1);
			}
			if (event.key === 'ArrowDown') {
				this.orbit.elevation = Math.max(0.12, this.orbit.elevation - 0.1);
			}
			if (event.key === '+' || event.key === '=') {
				this.orbit.zoom = Math.min(5, this.orbit.zoom * 1.1);
			}
			if (event.key === '-') {
				this.orbit.zoom = Math.max(0.25, this.orbit.zoom / 1.1);
			}
			this.render();
		});
		on('keyup', (event) => this.held.delete(event.code));
		on('blur', () => {
			this.held.clear();
		});
		this.resize = new ResizeObserver(() => {
			this.render();
		});
		this.resize.observe(canvas);
	}
	reset(): void {
		Object.assign(this.orbit, defaultOrbit());
		this.focused = false;
		this.draw();
	}
	/** Moves continuously while WASD/QE are held: A/D pan, Q/E lower/raise, W/S zoom in/out. */
	private readonly move = (time: number) => {
		const seconds = Math.min(0.1, (time - this.last) / 1000);
		const held = (code: string) => (this.held.has(code) ? 1 : 0);
		const right = (held('KeyD') - held('KeyA')) * this.span * seconds;
		const up = (held('KeyE') - held('KeyQ')) * this.span * seconds;
		const a = this.orbit.azimuth;
		this.last = time;
		this.orbit.pan = this.orbit.pan.map((v, i) => v + [-Math.sin(a) * right, Math.cos(a) * right, up][i]);
		this.orbit.zoom = Math.max(
			0.25,
			Math.min(5, this.orbit.zoom * Math.exp((held('KeyW') - held('KeyS')) * 1.5 * seconds)),
		);
		this.render();
		this.frame = this.held.size > 0 ? requestAnimationFrame(this.move) : 0;
	};
	destroy(): void {
		cancelAnimationFrame(this.frame);
		for (const remove of this.listeners) {
			remove();
		}
		this.resize.disconnect();
		if (this.content) {
			dispose(this.content);
		}
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
		if (this.content) {
			dispose(this.content);
		}
		const { root, center, extent, focused, status } = buildScene(this.provider());
		const styles = getComputedStyle(this.canvas);
		const palette = new Map<string, THREE.Color>();
		this.content = root;
		this.scene.add(root);
		root.traverse((object) => {
			if (!(object instanceof LineSegments2)) {
				return;
			}
			if (!palette.has(object.name)) {
				palette.set(
					object.name,
					this.color(isProperty(object.name) ? styles.getPropertyValue(`--${object.name}`).trim() : object.name),
				);
			}
			object.material.color.copy(palette.get(object.name)!);
		});
		this.status.textContent = status;
		if (!this.focused) {
			this.framing = { center, extent };
			this.focused = focused;
		}
		this.render();
	}
	/** Renders the current scene from the current orbit. */
	private render(): void {
		const { canvas, camera: viewCamera, labels } = this;
		const { center, extent } = this.framing;
		const width = canvas.clientWidth;
		const height = canvas.clientHeight;
		if (!width || !height) {
			return;
		}
		this.renderer.setSize(width, height, false);
		labels.setSize(width, height);
		Object.assign(labels.domElement.style, { left: `${canvas.offsetLeft}px`, top: `${canvas.offsetTop}px` });
		// Orthographic view of the orbit; the target sits slightly below the middle like a turntable.
		const { azimuth: a, elevation: e, zoom, pan } = this.orbit;
		const metres = 1 / Math.min(width / extent[0], height / extent[1]);
		const target = new THREE.Vector3().fromArray(center.map((v, i) => v + (pan[i] ?? 0)));
		this.span = (height * metres) / zoom;
		Object.assign(viewCamera, {
			bottom: -height * 0.44 * metres,
			far: 200,
			left: (-width / 2) * metres,
			near: 0,
			right: (width / 2) * metres,
			top: height * 0.56 * metres,
			zoom,
		});
		viewCamera.position
			.set(Math.cos(e) * Math.cos(a), Math.cos(e) * Math.sin(a), Math.sin(e))
			.multiplyScalar(100)
			.add(target);
		viewCamera.up.set(-Math.sin(e) * Math.cos(a), -Math.sin(e) * Math.sin(a), Math.cos(e));
		viewCamera.lookAt(target);
		viewCamera.updateProjectionMatrix();
		this.renderer.render(this.scene, viewCamera);
		labels.render(this.scene, viewCamera);
	}
}
