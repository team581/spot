import { useEffect, useRef, useLayoutEffect } from 'react';
import { useStatus } from '../queries';
import { usePreview, previewData } from './Feed';
import { theme } from '../theme';
import type { Camera, Geometry } from '../types';
import { cn } from 'cn';
import { Button } from '@/components/ui/button';
import { SpotViewer, type ViewerState } from '@spot/camera-viewer';
export default function GeometryViewer({
	camera: c,
	inspection = false,
	geometry,
}: {
	camera: Camera;
	inspection?: boolean;
	geometry?: Geometry | null;
}) {
	const status = useStatus(),
		preview = usePreview(c.identity),
		canvas = useRef<HTMLCanvasElement>(null),
		viewer = useRef<SpotViewer | null>(null);
	const latest = useRef<ViewerState>({ inspection });
	useLayoutEffect(() => {
		latest.current = {
			geometry: inspection ? geometry : preview.paused ? preview.held?.geometry : c.geometry,
			field: preview.paused ? preview.held?.field : status.field,
			data: previewData(preview),
			inspection,
		};
	});
	useEffect(() => {
		if (!canvas.current) return;
		const instance = new SpotViewer(canvas.current, () => latest.current);
		viewer.current = instance;
		instance.draw();
		const unsubscribe = theme.subscribe(() => instance.draw());
		return () => {
			unsubscribe();
			instance.destroy();
			viewer.current = null;
		};
	}, []);
	useEffect(() => {
		viewer.current?.draw();
	});
	return (
		<div
			className={cn(
				'relative min-h-48 min-w-0 overflow-hidden rounded-lg border bg-card',
				inspection && 'h-[420px] md:h-[600px]',
			)}
		>
			<canvas
				className="block size-full min-h-48 touch-none"
				ref={canvas}
				id="geometry-canvas"
				width={inspection ? 1000 : 700}
				height={inspection ? 720 : 350}
				tabIndex={0}
				aria-label={
					inspection
						? 'Robot geometry in WPILib NWU. Arrow keys orbit; A/D pan; Q/E down/up; W/S and plus/minus zoom'
						: '3D camera and observed tags. Arrow keys orbit; A/D pan; Q/E down/up; W/S and plus/minus zoom'
				}
			/>
			<Button variant="outline" className="absolute top-3 right-3" onClick={() => viewer.current?.reset()}>
				Reset view
			</Button>
		</div>
	);
}
