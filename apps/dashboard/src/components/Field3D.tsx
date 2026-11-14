import { useEffect, useRef } from 'react';
import { cn } from 'cn';
import { SpotViewer } from '@spot/camera-viewer';
import type { CameraImage, FieldCamera as ViewerCamera, ViewerState } from '@spot/camera-viewer';
import type { CameraConfig, FieldView } from '../api';
import type { Candidate, Detections } from '../detections';
import { fmt } from './common';
import { Button } from '@/components/ui/button';

const PALETTE = ['#2f7fc1', '#d9822b', '#2e9d5b', '#c8467a', '#8a5cc7', '#1f9a96', '#b59a12', '#d4553a'];
/** A stable color per camera, from its position among the sorted camera names. */
const cameraColor = (names: string[], name: string) =>
	PALETTE[Math.max(0, names.toSorted().indexOf(name)) % PALETTE.length];

export interface FieldCamera {
	name: string;
	config: CameraConfig;
	detections: Detections | undefined;
	/** Drawn in front of the camera, undistorted and placed with its calibration at the image's size or Spot's assumed one. */
	image: ImageBitmap | undefined;
}

/** The intrinsics Spot assumes for an uncalibrated camera; matches `Calibration::assumed` in the vision service. */
function assumed(width: number, height: number) {
	const [sx, sy] = [width / 1280, height / 800];
	return {
		cx: 644.0110163765805 * sx,
		cy: 447.8047664027805 * sy,
		fx: 799.4949524650956 * sx,
		fy: 799.8320596652597 * sy,
		distortion: [
			-0.08158965422395571, 0.08184871658046705, 0.00036991351895525955, 0.0006269072380960263, -0.062389853780706106,
		],
	};
}

function cameraImage({ config, image }: FieldCamera): CameraImage | undefined {
	// Closed bitmaps have no size and can't be drawn.
	if (!image?.width) {
		return undefined;
	}
	const { cx, cy, fx, fy, distortion } =
		config.calibrations?.[`${image.width}x${image.height}`] ?? assumed(image.width, image.height);
	return { bitmap: image, cx, cy, fx, fy, distortion };
}

function viewerState(field: FieldView | null | undefined, cameras: FieldCamera[]): ViewerState {
	const names = cameras.map((c) => c.name);
	const viewerCameras = cameras.map((c): ViewerCamera => ({
		name: c.name,
		pose: c.config.mount ?? {},
		color: cameraColor(names, c.name),
		image: cameraImage(c),
		robot: c.detections?.estimate?.primary ?? null,
		tags: c.detections?.tags.filter((t) => t.used).map((t) => t.id) ?? [],
	}));
	// Without a field layout there is nowhere to put estimates; show the mounts on the robot instead.
	return field ? { kind: 'field', field, cameras: viewerCameras } : { kind: 'robot', mounts: viewerCameras };
}

const median = (values: number[]) => {
	const sorted = values.toSorted((a, b) => a - b);
	const middle = sorted.length / 2;
	return sorted.length % 2 ? sorted[Math.floor(middle)] : (sorted[middle - 1] + sorted[middle]) / 2;
};

/** Each camera's robot estimate against the median of all of them; mount errors show up as outliers. */
function agreement(cameras: FieldCamera[]) {
	const estimates = cameras.flatMap((c) =>
		c.detections?.estimate ? [[c.name, c.detections.estimate.primary] as const] : [],
	);
	if (estimates.length < 2) {
		return new Map<string, { distance: number; yaw: number }>();
	}
	// Unwrap yaws around the first so the median works across ±180°.
	const first = estimates[0][1].yaw;
	const yaw = (c: Candidate) => first + ((((c.yaw - first) % 360) + 540) % 360) - 180;
	const x = median(estimates.map(([, c]) => c.x));
	const y = median(estimates.map(([, c]) => c.y));
	const heading = median(estimates.map(([, c]) => yaw(c)));
	return new Map(
		estimates.map(([name, c]) => [name, { distance: Math.hypot(c.x - x, c.y - y), yaw: Math.abs(yaw(c) - heading) }]),
	);
}

/**
 * The field with each camera's robot estimate in the camera's color, its body on that robot, and
 * lines to the tags it used. The robots overlap when mounts and calibrations agree.
 */
export function Field3D({
	field,
	cameras,
	className,
}: {
	field: FieldView | null | undefined;
	cameras: FieldCamera[];
	className?: string;
}) {
	const canvas = useRef<HTMLCanvasElement>(null);
	const viewer = useRef<SpotViewer>(null);
	const state = useRef<ViewerState>({ kind: 'robot', mounts: [] });
	const names = cameras.map((c) => c.name);
	const offsets = agreement(cameras);

	useEffect(() => {
		const v = new SpotViewer(canvas.current!, () => state.current);
		viewer.current = v;
		return () => {
			v.destroy();
			viewer.current = null;
		};
	}, []);
	useEffect(() => {
		state.current = viewerState(field, cameras);
		viewer.current?.draw();
	});

	return (
		<div className={cn('flex flex-col gap-3', className)}>
			<div className="relative overflow-hidden rounded-md border">
				<canvas
					ref={canvas}
					tabIndex={0}
					aria-label="3D field view. Drag to orbit, scroll or W/S to zoom, A/D/Q/E to pan."
					className="block aspect-video max-h-[70vh] min-h-72 w-full touch-none outline-none"
				/>
				<Button
					size="sm"
					variant="secondary"
					className="absolute top-2 right-2"
					onClick={() => viewer.current?.reset()}
				>
					Reset view
				</Button>
			</div>
			<ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
				{cameras.map((c) => {
					const estimate = c.detections?.estimate;
					const used = c.detections?.tags.filter((t) => t.used).length ?? 0;
					const offset = offsets.get(c.name);
					return (
						<li key={c.name} className="flex items-center gap-2">
							<span className="size-2.5 rounded-full" style={{ background: cameraColor(names, c.name) }} />
							<strong className="font-medium">{c.name}</strong>
							<span className="text-muted-foreground">
								{estimate
									? [
											`${used} ${used === 1 ? 'tag' : 'tags'}`,
											offset ? `Δ ${fmt(offset.distance * 100, 0)} cm, ${fmt(offset.yaw)}°` : null,
											`z ${fmt(estimate.primary.z * 100, 0)} cm`,
										]
											.filter(Boolean)
											.join(' · ')
									: c.detections
										? 'No estimate'
										: 'No data'}
							</span>
						</li>
					);
				})}
			</ul>
			{field ? null : (
				<p className="text-sm text-muted-foreground">
					No field layout from robot code, so mounts are shown on the robot without estimates.
				</p>
			)}
		</div>
	);
}
