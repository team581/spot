import { cn } from 'cn';
import { useDetections, useImage } from '../live';
import type { Detections } from '../detections';

/** The camera's live image with tag outlines, green where the tag contributed to the pose. */
export function LiveView({ camera, className }: { camera: string; className?: string }) {
	return <CameraImage image={useImage(camera)} detections={useDetections(camera)} className={className} />;
}

/** A camera image with tag outlines, green where the tag contributed to the pose. */
export function CameraImage({
	image,
	detections: d,
	className,
}: {
	image: string | undefined;
	detections: Detections | undefined;
	className?: string;
}) {
	return (
		<div
			className={cn('relative overflow-hidden rounded-md bg-feed', className)}
			style={{ aspectRatio: d ? `${d.width} / ${d.height}` : '16 / 10' }}
		>
			{image ? (
				<img src={image} alt="" className="absolute inset-0 size-full object-contain" />
			) : (
				<span className="absolute inset-0 grid place-items-center text-sm text-white/70">Waiting for image</span>
			)}
			{d ? (
				<svg viewBox={`0 0 ${d.width} ${d.height}`} className="absolute inset-0 size-full">
					{d.tags.map((tag) => {
						const [x, y] = tag.corners[3] ?? [0, 0];
						const color = tag.used ? '#79d6a5' : '#edc06c';
						return (
							<g key={`${tag.id}:${tag.corners.join(',')}`}>
								<polygon
									points={tag.corners.join(' ')}
									fill="none"
									stroke={color}
									strokeWidth={3}
									vectorEffect="non-scaling-stroke"
								/>
								<text x={x} y={y - 8} fill={color} fontSize={d.height / 25} fontWeight={600}>
									{tag.id}
								</text>
							</g>
						);
					})}
				</svg>
			) : null}
		</div>
	);
}
