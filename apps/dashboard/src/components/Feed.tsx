import { useEffect, useLayoutEffect, useRef, useSyncExternalStore, useCallback } from 'react';
import { useDashboard, useServiceError } from '../dashboard';
import { useStatus } from '../queries';
import { age } from './common';
import { cn } from 'cn';
import type { Preview } from '../previews';
import type { Camera, Status } from '../types';
export function usePreview(id: string) {
	const { previews } = useDashboard();
	const subscribe = useCallback((listener: () => void) => previews.subscribe(id, listener), [id, previews]);
	const snapshot = useCallback(() => previews.get(id), [id, previews]);
	return useSyncExternalStore(subscribe, snapshot);
}
export function previewData(view: Preview) {
	return view.paused ? view.held : view.data;
}
export function currentFrame(view: Preview, camera: Camera, status: Status) {
	const data = previewData(view);
	return Boolean(
		data?.processed &&
		!data.stale &&
		(view.paused || (camera.age_s! < 0.5 && data.generation === status.applied_generation)),
	);
}
export function frameAge(view: Preview) {
	const data = previewData(view);
	return data
		? data.age_s + (performance.now() - (view.paused ? view.held?.heldAt : view.received)!) / 1000
		: undefined;
}
export function Feed({
	id,
	outlines = true,
	calibration = false,
	className,
}: {
	id: string;
	className?: string;
	outlines?: boolean;
	calibration?: boolean;
}) {
	const { previews } = useDashboard(),
		status = useStatus(),
		serviceError = useServiceError();
	const view = usePreview(id),
		c = status.cameras.find((c) => c.identity === id);
	const canvas = useRef<HTMLCanvasElement>(null),
		element = useRef<HTMLDivElement>(null);
	const data = previewData(view),
		bitmap = view.paused ? view.held?.bitmap : view.bitmap;
	const imageStale = !view.paused && Boolean(serviceError || !c?.connected || c.age_s! > 0.5 || data?.stale);
	const stale = imageStale || (!view.paused && data?.generation !== status.applied_generation);
	useEffect(() => {
		if (element.current) return previews.register(id, element.current);
	}, [id, previews]);
	useLayoutEffect(() => {
		const el = canvas.current,
			ctx = el?.getContext('2d');
		if (!el || !ctx) return;
		ctx.clearRect(0, 0, el.width, el.height);
		if (!bitmap?.width || !bitmap.height) return;
		const scale = Math.min(el.width / bitmap.width, el.height / bitmap.height),
			w = bitmap.width * scale,
			h = bitmap.height * scale,
			x = (el.width - w) / 2,
			y = (el.height - h) / 2;
		ctx.drawImage(bitmap, x, y, w, h);
		const coverage = status.calibration.cameras[id]?.coverage?.coverage_particles;
		if (!stale && calibration)
			for (const p of (coverage ?? []).slice(0, 6912)) {
				if (![p.x, p.y, p.progress].every(Number.isFinite)) continue;
				ctx.fillStyle = p.progress >= 1 ? 'rgba(85,230,155,.46)' : 'rgba(255,216,90,.7)';
				ctx.beginPath();
				ctx.arc(x + p.x * w, y + p.y * h, p.progress >= 1 ? 1.5 : 1.7, 0, Math.PI * 2);
				ctx.fill();
			}
		if (!stale && outlines) {
			ctx.strokeStyle = ctx.fillStyle = '#79D6A5';
			ctx.lineWidth = 2;
			ctx.font = '14px system-ui';
			for (const tag of data?.tags ?? []) {
				ctx.beginPath();
				tag.corners.forEach((p, i) => {
					i
						? ctx.lineTo(x + (p[0] / data!.width) * w, y + (p[1] / data!.height) * h)
						: ctx.moveTo(x + (p[0] / data!.width) * w, y + (p[1] / data!.height) * h);
				});
				ctx.closePath();
				ctx.stroke();
				const p = tag.corners[0];
				if (p) ctx.fillText('#' + tag.id, x + (p[0] / data!.width) * w, y + (p[1] / data!.height) * h - 5);
			}
		}
		if (coverage && !stale && calibration)
			for (const p of coverage) {
				ctx.fillStyle = p.progress >= 1 ? '#79D6A5' : '#E5BA72';
				ctx.beginPath();
				ctx.arc(x + p.x * w, y + p.y * h, 2, 0, Math.PI * 2);
				ctx.fill();
			}
	}, [bitmap, data, stale, outlines, calibration, status.calibration, id]);
	const text = view.paused
		? `Paused · frame ${data?.sequence ?? '—'} · ${age(frameAge(view))}`
		: serviceError
			? 'Service disconnected · last image'
			: !c?.connected
				? c?.health === 'Disabled'
					? 'Disabled in code'
					: c?.present
						? c.fault || 'Waiting for image'
						: 'Disconnected'
				: imageStale && bitmap
					? 'Stale image · outlines hidden'
					: !bitmap
						? 'Waiting for image'
						: stale
							? 'Live image · waiting for current robot profile'
							: '';
	return (
		<div
			className={cn(
				'relative flex aspect-[1.875] items-center justify-center overflow-hidden rounded-md bg-feed',
				className,
			)}
			data-feed={id}
			ref={element}
		>
			<canvas
				ref={canvas}
				width="960"
				height="540"
				aria-label="Camera image"
				className="block size-full object-contain"
			/>
			<span className="image-state absolute bottom-3 left-3 max-w-max rounded bg-black/75 px-2 py-1 text-xs text-white empty:hidden">
				{text}
			</span>
		</div>
	);
}
