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
interface Shape {
	points: number[][];
	stroke: string;
	width: number;
	fill: string | null;
	layer: number;
	depth: number;
}
interface Label {
	text: string;
	p: number[];
	color: string;
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
export class SpotViewer {
	readonly canvas: HTMLCanvasElement;
	private provider: () => ViewerState;
	readonly orbit: { azimuth: number; elevation: number; zoom: number } = { azimuth: -1.05, elevation: 0.72, zoom: 1 };
	private drag: number[] | null = null;
	private listeners: (() => void)[] = [];
	private resize: ResizeObserver;

	constructor(canvas: HTMLCanvasElement, provider: () => ViewerState) {
		this.canvas = canvas;
		this.provider = provider;
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
				this.draw();
			},
			{ passive: false },
		);
		on('keydown', (event) => {
			if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-'].includes(event.key)) return;
			event.preventDefault();
			if (event.key === 'ArrowLeft') this.orbit.azimuth -= 0.1;
			if (event.key === 'ArrowRight') this.orbit.azimuth += 0.1;
			if (event.key === 'ArrowUp') this.orbit.elevation = Math.min(1.5, this.orbit.elevation + 0.1);
			if (event.key === 'ArrowDown') this.orbit.elevation = Math.max(0.12, this.orbit.elevation - 0.1);
			if (event.key === '+' || event.key === '=') this.orbit.zoom = Math.min(5, this.orbit.zoom * 1.1);
			if (event.key === '-') this.orbit.zoom = Math.max(0.25, this.orbit.zoom / 1.1);
			this.draw();
		});
		this.resize = new ResizeObserver(() => this.draw());
		this.resize.observe(canvas);
	}
	reset(): void {
		Object.assign(this.orbit, { azimuth: -1.05, elevation: 0.72, zoom: 1 });
		this.draw();
	}
	destroy(): void {
		for (const remove of this.listeners) remove();
		this.resize.disconnect();
	}
	draw(): void {
		const { geometry, field, data, inspection, mounts, selectedName, drivebase } = this.provider(),
			canvas = this.canvas,
			ctx = canvas.getContext('2d')!,
			W = canvas.width,
			H = canvas.height,
			styles = getComputedStyle(document.documentElement),
			ink = styles.getPropertyValue('--ink').trim(),
			lineColor = styles.getPropertyValue('--line').trim(),
			blue = styles.getPropertyValue('--blue').trim(),
			accent = styles.getPropertyValue('--accent-text').trim(),
			muted = styles.getPropertyValue('--muted-foreground').trim(),
			green = styles.getPropertyValue('--good').trim();
		ctx.clearRect(0, 0, W, H);
		ctx.lineCap = 'round';
		ctx.lineJoin = 'round';
		const current = data && !data.stale && data.candidates?.length,
			candidates = current ? data!.candidates! : [],
			selected = candidates.reduce<Candidate | null>(
				(a, b) => (!a || (b.error_px ?? NaN) < (a.error_px ?? NaN) ? b : a),
				null,
			),
			world = !inspection && selected && field ? { selected, field } : null;
		const center = world ? [world.field.length / 2, world.field.width / 2, 0] : [0, 0, 0.3],
			scale =
				(world ? Math.min(W / (world.field.length + 2), H / (world.field.width + 2)) : Math.min(W, H) / 3) *
				this.orbit.zoom;
		const ca = Math.cos(this.orbit.azimuth),
			sa = Math.sin(this.orbit.azimuth),
			ce = Math.cos(this.orbit.elevation),
			se = Math.sin(this.orbit.elevation);
		const project = (p: number[]) => {
			const [x, y, z] = p.map((v, i) => v - center[i]);
			return [
				W / 2 + (-sa * x + ca * y) * scale,
				H * 0.56 - (-se * ca * x - se * sa * y + ce * z) * scale,
				ce * ca * x + ce * sa * y + se * z,
			];
		};
		let layer = 0;
		const shapes: Shape[] = [],
			labels: Label[] = [];
		const polygon = (points: number[][], stroke: string, width = 1, fill: string | null = null) =>
			shapes.push({
				points,
				stroke,
				width,
				fill,
				layer,
				depth: points.reduce((s, p) => s + project(p)[2], 0) / points.length,
			});
		const line = (a: number[], b: number[], color: string, width = 1) => polygon([a, b], color, width);
		const label = (text: string, p: number[], color = muted) => labels.push({ text, p, color });
		const point = (pose: Pose, p: number[]) => rotate(pose.quaternion, p).map((v, i) => v + pose.translation[i]);
		function box(pose: Pose, size: number[], color: string) {
			const base = [
					[-size[0] / 2, -size[1] / 2, 0],
					[size[0] / 2, -size[1] / 2, 0],
					[size[0] / 2, size[1] / 2, 0],
					[-size[0] / 2, size[1] / 2, 0],
				].map((p) => point(pose, p)),
				top = [
					[-size[0] / 2, -size[1] / 2, size[2]],
					[size[0] / 2, -size[1] / 2, size[2]],
					[size[0] / 2, size[1] / 2, size[2]],
					[-size[0] / 2, size[1] / 2, size[2]],
				].map((p) => point(pose, p));
			polygon(base, color, 1.5);
			polygon(top, color, 1.5);
			for (let i = 0; i < 4; i++) line(base[i], top[i], color, 1.5);
		}
		function arrow(pose: Pose, direction: number[], text: string, color: string) {
			const a = pose.translation,
				b = point(pose, direction);
			line(a, b, color, 2);
			label(text, b, color);
			const d = direction.map((v) => v * 0.82),
				side = direction[0]
					? [
							[d[0], -0.08, d[2]],
							[d[0], 0.08, d[2]],
						]
					: [
							[d[0] - 0.08, d[1], d[2]],
							[d[0] + 0.08, d[1], d[2]],
						];
			for (const p of side) line(b, point(pose, p), color, 2);
		}
		if (world) {
			polygon(
				[
					[0, 0, 0],
					[world.field.length, 0, 0],
					[world.field.length, world.field.width, 0],
					[0, world.field.width, 0],
				],
				lineColor,
				1.5,
			);
			for (let x = 1; x < world.field.length; x++) line([x, 0, 0], [x, world.field.width, 0], lineColor);
			for (let y = 1; y < world.field.width; y++) line([0, y, 0], [world.field.length, y, 0], lineColor);
			label('Blue-wall-right origin', [0, 0, 0], blue);
		} else {
			for (let i = -3; i <= 3; i++) {
				line([i * 0.4, -1.2, 0], [i * 0.4, 1.2, 0], lineColor);
				line([-1.2, i * 0.4, 0], [1.2, i * 0.4, 0], lineColor);
			}
		}
		layer = 1;
		const chassis =
			world && geometry ? robotPose(world.selected, geometry) : { translation: [0, 0, 0], quaternion: [1, 0, 0, 0] };
		if (!mounts) box(chassis, [1, 0.8, 0.15], muted);
		else if (
			drivebase?.visible &&
			Number.isFinite(drivebase.length) &&
			Number.isFinite(drivebase.width) &&
			drivebase.length > 0 &&
			drivebase.width > 0
		) {
			// Footprint only: X is length, Y is width. No guessed chassis height.
			polygon(
				[
					[-drivebase.length / 2, -drivebase.width / 2, 0],
					[drivebase.length / 2, -drivebase.width / 2, 0],
					[drivebase.length / 2, drivebase.width / 2, 0],
					[-drivebase.length / 2, drivebase.width / 2, 0],
				],
				accent,
				2.5,
			);
		}
		arrow(chassis, [0, 0, 0.8], '+Z up', muted);
		arrow(chassis, [0.95, 0, 0.03], 'Front · +X', accent);
		arrow(chassis, [0, 0.65, 0.03], '+Y left', muted);
		const drawCamera = (pose: Pose, color: string, name: string) => {
			box(pose, [0.18, 0.14, 0.12], color);
			arrow(pose, [0.7, 0, 0], 'Lens', color);
			line(point(pose, [0, 0, 0.12]), point(pose, [0, 0, 0.3]), color, 2);
			label(name, point(pose, [0, 0, 0.35]), color);
		};
		if (mounts) {
			for (const mount of mounts) {
				drawCamera(mount, mount.name === selectedName ? blue : muted, mount.name);
				arrow(mount, [0, 0.25, 0], '+Y', green);
				arrow(mount, [0, 0, 0.25], '+Z', accent);
			}
		} else if (world) {
			for (const candidate of candidates)
				drawCamera(
					candidate,
					candidate === selected ? blue : styles.getPropertyValue('--warning').trim(),
					candidate === selected ? 'Selected camera' : 'Alternate camera',
				);
			const seen = new Set(data!.tags.map((t) => t.id));
			for (const tag of world.field.tags || []) {
				const half = tag.size / 2,
					pose = { translation: tag.translation, quaternion: tag.quaternion };
				polygon(
					[
						[0, -half, -half],
						[0, half, -half],
						[0, half, half],
						[0, -half, half],
					].map((p) => point(pose, p)),
					seen.has(tag.id) ? green : muted,
					1.5,
				);
				if (seen.has(tag.id)) {
					line(world.selected.translation, tag.translation, green);
					label('#' + tag.id, tag.translation, green);
				}
			}
		} else if (geometry) drawCamera(geometry, blue, 'Camera · robot NWU');
		shapes.sort((a, b) => a.layer - b.layer || (a.layer ? a.depth - b.depth : 0));
		for (const s of shapes) {
			ctx.beginPath();
			s.points.forEach((p, i) => {
				const [x, y] = project(p);
				i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
			});
			if (s.points.length > 2) ctx.closePath();
			ctx.strokeStyle = s.stroke;
			ctx.lineWidth = s.width;
			ctx.stroke();
		}
		ctx.font = '14px system-ui';
		ctx.textAlign = 'center';
		for (const item of labels) {
			const [x, y] = project(item.p);
			ctx.fillStyle = item.color;
			ctx.fillText(item.text, x, y - 8);
		}
		ctx.font = '13px system-ui';
		ctx.textAlign = 'left';
		ctx.fillStyle = muted;
		if (!geometry && !mounts) ctx.fillText('Camera geometry unavailable', 16, 28);
		else if (!mounts && !inspection && !current) ctx.fillText('No current field pose · camera mount shown', 16, 28);
		ctx.fillText(
			mounts ? 'Metres · grid 0.4 m · camera bodies schematic' : 'Drivebase outline is schematic',
			16,
			H - 18,
		);
		ctx.fillStyle = ink;
	}
}
