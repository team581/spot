import { useEffect, useRef, useLayoutEffect } from 'react';
import { useDashboard } from '../dashboard';
import { usePreview, previewData } from './Feed';
import { theme } from '../theme';
import type { Camera, Frame, Geometry, Status } from '../types';
import '@spot/camera-viewer';
interface ViewerState {
	camera?: Camera;
	geometry?: Geometry | null;
	field?: Status['field'];
	data?: Frame;
	inspection: boolean;
}
interface ViewerInstance {
	draw: () => void;
	reset: () => void;
	destroy: () => void;
}
declare global {
	var SpotViewer: {
		new (canvas: HTMLCanvasElement, provider: () => ViewerState): ViewerInstance;
		cameraAngles: (q: number[]) => number[];
		cameraQuaternion: (yaw: number, pitch: number, roll: number) => number[];
	};
}
export default function GeometryViewer({
	camera: c,
	inspection = false,
	geometry,
}: {
	camera: Camera;
	inspection?: boolean;
	geometry?: Geometry | null;
}) {
	const { status } = useDashboard(),
		preview = usePreview(c.identity),
		canvas = useRef<HTMLCanvasElement>(null),
		viewer = useRef<ViewerInstance | null>(null);
	const latest = useRef<ViewerState>({ inspection });
	useLayoutEffect(() => {
		latest.current = {
			camera: c,
			geometry: inspection ? geometry : preview.paused ? preview.held?.geometry : c.geometry,
			field: preview.paused ? preview.held?.field : status.field,
			data: previewData(preview),
			inspection,
		};
	});
	useEffect(() => {
		if (!canvas.current) return;
		const instance = new globalThis.SpotViewer(canvas.current, () => latest.current);
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
		<div className={'viewer ' + (inspection ? 'geometry-view' : '')}>
			<canvas
				ref={canvas}
				id="geometry-canvas"
				width={inspection ? 1000 : 700}
				height={inspection ? 720 : 350}
				tabIndex={0}
				aria-label={
					inspection
						? 'Robot geometry in WPILib NWU. Arrow keys orbit; plus/minus zoom'
						: '3D camera and observed tags. Arrow keys orbit; plus/minus zoom'
				}
			/>
			<button className="reset-view" onClick={() => viewer.current?.reset()}>
				Reset view
			</button>
			{inspection ? (
				<span className="frame-label">Inspection · production geometry from robot code</span>
			) : (
				<a className="frame-label" href={'#camera/' + encodeURIComponent(c.identity) + '/geometry'}>
					Geometry · WPILib NWU
				</a>
			)}
		</div>
	);
}
