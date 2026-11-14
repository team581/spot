/// <reference types="vite-plus/client" />
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
// SWYFT Robotics' OV9281 USB-C camera, converted from its STEP file without the parts hidden inside the case.
import cameraModelUrl from './camera.glb?url';

/** WPILib translation in metres and `Rotation3d(roll, pitch, yaw)` in degrees; omitted values are 0. */
export interface Pose {
	x?: number;
	y?: number;
	z?: number;
	roll?: number;
	pitch?: number;
	yaw?: number;
}
/** A camera frame and the pinhole intrinsics, in its pixels, that place it in front of the camera. */
export interface CameraImage {
	bitmap: ImageBitmap;
	fx: number;
	fy: number;
	cx: number;
	cy: number;
}
/** A camera and its robot-to-camera transform. */
export interface Mount {
	name: string;
	pose: Pose;
	/** Any CSS color; robot views default to muted, or blue when selected. */
	color?: string;
	/** Drawn in the camera's view frustum. */
	image?: CameraImage;
}
/** A camera on the field: its mount, plus what it currently sees. */
export interface FieldCamera extends Mount {
	/** Used for this camera's robot, body, and tag lines. */
	color: string;
	/** The robot's field pose estimated from this camera, or null without one. */
	robot: Pose | null;
	/** IDs of the tags the estimate used. */
	tags: number[];
}
/** A WPILib field layout tag: its centre in metres and its rotation as a quaternion. */
export interface FieldTag {
	id: number;
	x: number;
	y: number;
	z: number;
	qw: number;
	qx: number;
	qy: number;
	qz: number;
}
export type ViewerState =
	| {
			/** The field with each camera's robot estimate, mount, and the tags it used. */
			kind: 'field';
			/** Metres; 0 fits the field to its tags. */
			field: { length: number; width: number; tags: FieldTag[] };
			cameras: FieldCamera[];
	  }
	| {
			/** Camera mounts on a robot at the origin. */
			kind: 'robot';
			mounts: Mount[];
			selectedName?: string;
			drivebase?: { visible: boolean; length: number; width: number };
	  };
/** A CSS custom property name (without `--`), or any other CSS color. */
type Color = 'line' | 'blue' | 'accent-text' | 'muted-foreground' | 'good' | 'warning' | (string & {});
/** FRC AprilTag (36h11) edge length in metres, across the outer black border. */
const TAG_SIZE = 0.1651;
/** Metres in front of a camera to draw its image. */
const IMAGE_DISTANCE = 0.5;
interface Placed {
	position: THREE.Vector3;
	quaternion: THREE.Quaternion;
}
const radians = THREE.MathUtils.degToRad;
const placed = ({ x = 0, y = 0, z = 0, roll = 0, pitch = 0, yaw = 0 }: Pose): Placed => ({
	position: new THREE.Vector3(x, y, z),
	quaternion: new THREE.Quaternion().setFromEuler(new THREE.Euler(radians(roll), radians(pitch), radians(yaw), 'ZYX')),
});
const isProperty = (color: string) => /^[\w-]+$/.test(color);
/** The camera model looking along +X with its lens front at the origin, once loaded. */
let cameraModel: THREE.Object3D | undefined;
async function parseCameraModel() {
	const { scene } = await new GLTFLoader().loadAsync(cameraModelUrl);
	// The model's lens looks along +Z with its front 18.1 mm up; the USB-C port (-Y) is image down.
	scene.applyMatrix4(new THREE.Matrix4().set(0, 0, 1, -0.0181, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1));
	scene.traverse((object) => {
		if (object instanceof THREE.Mesh && object.material instanceof THREE.MeshStandardMaterial) {
			object.material.metalness = 0;
			// The case takes the camera's color.
			object.userData.tinted = object.name.includes('CASE');
		}
	});
	cameraModel = scene;
}
let loadingCameraModel: Promise<void> | undefined;
export interface Scene {
	/** Lines and camera cases are named by their color; labels are `CSS2DObject`s. */
	root: THREE.Group;
	center: number[];
	/** Metres to fit in view at zoom 1. */
	extent: number[];
	/** Framed close on the robot's field pose; the viewer then holds this framing until reset. */
	focused: boolean;
	status: string;
}
function posed(parent: THREE.Object3D, pose: Placed): THREE.Group {
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
/** The camera model with its case in this color, or nothing until it loads. */
function body(parent: THREE.Object3D, color: Color) {
	if (!cameraModel) {
		return;
	}
	const model = cameraModel.clone();
	model.traverse((object) => {
		if (object instanceof THREE.Mesh && object.userData.tinted) {
			object.material = object.material.clone();
			object.name = color;
		}
	});
	parent.add(model);
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
/** The image on a plane in front of the camera, with lines from the lens to its corners. */
function view(parent: THREE.Object3D, { bitmap, fx, fy, cx, cy }: CameraImage, color: Color) {
	const d = IMAGE_DISTANCE;
	// The lens looks along +X; image right is -Y and image down is -Z.
	const corner = (u: number, v: number) => [d, ((cx - u) / fx) * d, ((cy - v) / fy) * d];
	const corners = [
		corner(0, 0),
		corner(bitmap.width, 0),
		corner(bitmap.width, bitmap.height),
		corner(0, bitmap.height),
	];
	const geometry = new THREE.BufferGeometry();
	geometry.setAttribute('position', new THREE.Float32BufferAttribute(corners.flat(), 3));
	geometry.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
	geometry.setIndex([0, 1, 2, 0, 2, 3]);
	const texture = new THREE.Texture(bitmap);
	// ImageBitmaps upload top row first, so v = 0 is the top of the image.
	texture.flipY = false;
	texture.colorSpace = THREE.SRGBColorSpace;
	texture.needsUpdate = true;
	parent.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ map: texture, side: THREE.DoubleSide })));
	loop(parent, corners, color, 1.5);
	segments(
		parent,
		corners.flatMap((p) => [[0, 0, 0], p]),
		color,
	);
}
function camera(parent: THREE.Object3D, pose: Placed, color: Color, name: string) {
	const group = posed(parent, pose);
	body(group, color);
	arrow(group, [0.7, 0, 0], '', color);
	label(group, name, [0, 0, 0.02], color);
	return group;
}
/** Builds the scene in WPILib NWU metres. Needs `document` for labels but no WebGL. */
export function buildScene(state: ViewerState): Scene {
	const root = new THREE.Group();
	const field = state.kind === 'field' ? state.field : undefined;
	const arena = field && {
		length: field.length > 0 ? field.length : Math.max(16.5, ...field.tags.map((t) => t.x)),
		width: field.width > 0 ? field.width : Math.max(8.1, ...field.tags.map((t) => t.y)),
	};
	const cameras = state.kind === 'field' ? state.cameras : [];
	const estimates = cameras.filter((c) => c.robot);
	// Cameras without an estimate ride on another camera's robot, or one at midfield.
	const reference: Placed = estimates[0]?.robot
		? placed(estimates[0].robot)
		: {
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
		const drivebase = state.kind === 'robot' ? state.drivebase : undefined;
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
		const corner = posed(root, placed({ x: -1.2, y: -1.2 }));
		arrow(corner, [0.8, 0, 0], '+X front', 'muted-foreground');
		arrow(corner, [0, 0.8, 0], '+Y left', 'muted-foreground');
	}
	if (state.kind === 'robot') {
		for (const mount of state.mounts) {
			const color = mount.color ?? (mount.name === state.selectedName ? 'blue' : 'muted-foreground');
			const group = camera(root, placed(mount.pose), color, mount.name);
			if (mount.image) {
				view(group, mount.image, color);
			}
		}
	} else if (field) {
		const robot = (chassis: THREE.Object3D, color: Color) => {
			box(chassis, [0.9, 0.9, 0.15], color);
			arrow(chassis, [0.75, 0, 0.15], '', color);
		};
		const tags = new Map(
			field.tags.map((t) => [
				t.id,
				{
					id: t.id,
					position: new THREE.Vector3(t.x, t.y, t.z),
					quaternion: new THREE.Quaternion(t.qx, t.qy, t.qz, t.qw).normalize(),
				},
			]),
		);
		const seen = new Map<number, Color>();
		if (estimates.length === 0) {
			robot(posed(root, reference), 'muted-foreground');
		}
		for (const c of cameras) {
			const chassis = posed(root, c.robot ? placed(c.robot) : reference);
			if (c.robot) {
				robot(chassis, c.color);
			}
			const mount = camera(chassis, placed(c.pose), c.color, c.name);
			if (c.image) {
				view(mount, c.image, c.color);
			}
			const position = mount.getWorldPosition(new THREE.Vector3());
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
			const half = TAG_SIZE / 2;
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
		// Tinted camera cases share the loaded model's geometry.
		if (object instanceof THREE.Mesh && object.userData.tinted) {
			object.material.dispose();
		}
		if (object instanceof THREE.Mesh && object.material instanceof THREE.MeshBasicMaterial) {
			object.geometry.dispose();
			object.material.map?.dispose();
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
	/** Movement keys held down, by `KeyboardEvent.code`. */
	private readonly held = new Set<string>();
	private frame = 0;
	private destroyed = false;
	private last = 0;
	private framing = { center: [0, 0, 0], extent: [3, 3] };
	/** Holds framing on the robot so flickering detections don't move the view. */
	private focused = false;
	private readonly listeners: (() => void)[] = [];
	private readonly resize: ResizeObserver;
	private readonly renderer: THREE.WebGLRenderer;
	private readonly labels = new CSS2DRenderer();
	private readonly status = document.createElement('div');
	private readonly scene = new THREE.Scene();
	private readonly camera = new THREE.OrthographicCamera();
	private readonly controls: OrbitControls;
	private content: THREE.Group | null = null;
	private readonly probe = document.createElement('canvas').getContext('2d', { willReadFrequently: true })!;

	constructor(canvas: HTMLCanvasElement, provider: () => ViewerState) {
		this.canvas = canvas;
		this.provider = provider;
		this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, canvas });
		this.renderer.setPixelRatio(devicePixelRatio);
		this.camera.up.set(0, 0, 1);
		// A headlight from above the view so the camera models show their shape from any angle.
		const light = new THREE.DirectionalLight('white', 2);
		light.position.set(0, 1, 0);
		light.target.position.set(0, 0, -1);
		this.camera.add(light, light.target);
		this.scene.add(this.camera, new THREE.AmbientLight('white', 1.5));
		this.controls = new OrbitControls(this.camera, canvas);
		this.controls.minPolarAngle = 0;
		this.controls.maxPolarAngle = Math.PI / 2;
		this.controls.minZoom = 0.25;
		this.controls.maxZoom = 5;
		this.controls.addEventListener('change', () => {
			Object.assign(this.orbit, {
				azimuth: this.controls.getAzimuthalAngle() - Math.PI / 2,
				elevation: Math.PI / 2 - this.controls.getPolarAngle(),
				pan: this.controls.target.clone().sub(new THREE.Vector3().fromArray(this.framing.center)).toArray(),
				zoom: this.camera.zoom,
			});
			this.render();
		});
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
		on('pointerdown', () => {
			canvas.focus();
		});
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
				this.controls.rotateLeft(0.1);
			}
			if (event.key === 'ArrowRight') {
				this.controls.rotateLeft(-0.1);
			}
			if (event.key === 'ArrowUp') {
				this.controls.rotateUp(0.1);
			}
			if (event.key === 'ArrowDown') {
				this.controls.rotateUp(-0.1);
			}
			if (event.key === '+' || event.key === '=') {
				this.controls.dollyIn(1 / 1.1);
			}
			if (event.key === '-') {
				this.controls.dollyOut(1 / 1.1);
			}
		});
		on('keyup', (event) => this.held.delete(event.code));
		on('blur', () => {
			this.held.clear();
		});
		this.resize = new ResizeObserver(() => {
			this.render();
		});
		this.resize.observe(canvas);
		void this.loadCameraModel();
	}
	/** Redraws with the camera model once it loads. */
	private async loadCameraModel() {
		loadingCameraModel ??= parseCameraModel();
		await loadingCameraModel;
		if (!this.destroyed) {
			this.draw();
		}
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
		const right = (held('KeyD') - held('KeyA')) * this.canvas.clientHeight * seconds;
		const span = (this.camera.top - this.camera.bottom) / this.camera.zoom;
		const up = (held('KeyE') - held('KeyQ')) * span * seconds;
		this.last = time;
		this.camera.position.z += up;
		this.controls.target.z += up;
		this.controls.pan(-right, 0);
		this.controls.dollyIn(Math.exp(-(held('KeyW') - held('KeyS')) * 1.5 * seconds));
		this.frame = this.held.size > 0 ? requestAnimationFrame(this.move) : 0;
	};
	destroy(): void {
		this.destroyed = true;
		cancelAnimationFrame(this.frame);
		for (const remove of this.listeners) {
			remove();
		}
		this.resize.disconnect();
		this.controls.dispose();
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
			const material =
				object instanceof LineSegments2
					? object.material
					: object instanceof THREE.Mesh &&
						  object.userData.tinted === true &&
						  object.material instanceof THREE.MeshStandardMaterial
						? object.material
						: undefined;
			if (!material) {
				return;
			}
			if (!palette.has(object.name)) {
				palette.set(
					object.name,
					this.color(isProperty(object.name) ? styles.getPropertyValue(`--${object.name}`).trim() : object.name),
				);
			}
			material.color.copy(palette.get(object.name)!);
		});
		this.status.textContent = status;
		if (!this.focused) {
			this.framing = { center, extent };
			this.focused = focused;
		}
		const { azimuth, elevation, pan, zoom } = this.orbit;
		this.controls.target.fromArray(this.framing.center).add(new THREE.Vector3().fromArray(pan));
		this.camera.position
			.set(100, 0, 0)
			.applyEuler(new THREE.Euler(0, -elevation, azimuth, 'ZYX'))
			.add(this.controls.target);
		this.camera.zoom = zoom;
		this.controls.update();
		this.render();
	}
	/** Renders the current scene from the current orbit. */
	private render(): void {
		const { canvas, camera: viewCamera, labels } = this;
		const { extent } = this.framing;
		const width = canvas.clientWidth;
		const height = canvas.clientHeight;
		if (!width || !height) {
			return;
		}
		this.renderer.setSize(width, height, false);
		labels.setSize(width, height);
		Object.assign(labels.domElement.style, { left: `${canvas.offsetLeft}px`, top: `${canvas.offsetTop}px` });
		// Orthographic view of the orbit; the target sits slightly below the middle like a turntable.
		const metres = 1 / Math.min(width / extent[0], height / extent[1]);
		Object.assign(viewCamera, {
			bottom: -height * 0.44 * metres,
			far: 200,
			left: (-width / 2) * metres,
			near: 0,
			right: (width / 2) * metres,
			top: height * 0.56 * metres,
		});
		viewCamera.updateProjectionMatrix();
		this.renderer.render(this.scene, viewCamera);
		labels.render(this.scene, viewCamera);
	}
}
