import { Link } from '@tanstack/react-router';
import { useServiceError } from '../dashboard';
import { useStatus } from '../queries';
import { Feed, usePreview } from '../components/Feed';
import { age, CalibrationState, Feedback, PageTitle, Panel } from '../components/common';
import { Card } from '@/components/ui/card';
import type { Camera } from '../types';
function Tile({ camera: c }: { camera: Camera }) {
	const view = usePreview(c.identity),
		captureFresh = c.connected && c.age_s != null && c.age_s < 0.5,
		fresh = c.connected && c.metrics?.detect_age_s != null && c.metrics.detect_age_s < 0.5;
	return (
		<Link
			className="tile group/tile rounded-lg text-foreground no-underline hover:no-underline"
			to="/cameras/$id"
			params={{ id: c.identity }}
			data-tile={c.identity}
		>
			<Card className="gap-0 py-0 transition-shadow group-hover/tile:ring-foreground/30">
				<header className="flex items-center justify-between px-4 py-3">
					<strong className="font-heading text-base">{c.name}</strong>
					<CalibrationState camera={c} />
				</header>
				<Feed id={c.identity} className="aspect-2/1 rounded-none" />
				<div className="flex justify-between gap-2 px-4 py-3 text-lg font-semibold sm:text-xl">
					<span title="Measured capture FPS; detection and preview rates are separate">
						{captureFresh && c.metrics?.captured && Number.isFinite(c.metrics.fps_capture)
							? `${Math.round(c.metrics.fps_capture!)} FPS`
							: '— FPS'}
					</span>
					<span>
						{view.data && !view.data.stale && fresh && view.data.processed ? `${view.data.tags.length} tags` : '— tags'}
					</span>
					<span>{age(c.age_s)}</span>
				</div>
			</Card>
		</Link>
	);
}
export default function Overview({ page }: { page: string }) {
	const status = useStatus(),
		serviceError = useServiceError();
	return (
		<>
			<PageTitle>{page === 'cameras' ? 'Cameras' : 'Overview'}</PageTitle>
			<div className="grid gap-6 md:grid-cols-2">
				{status.cameras.length ? (
					status.cameras.map((c) => <Tile key={c.identity} camera={c} />)
				) : (
					<Panel title="No cameras discovered" className="max-w-2xl">
						<p>Connect a powered USB camera. Discovery continues automatically.</p>
						<Link to="/help/$" params={{ _splat: 'operator/cameras/' }} hash="connect">
							Connection guide
						</Link>
					</Panel>
				)}
			</div>
			<Feedback id="page-feedback">{serviceError}</Feedback>
		</>
	);
}
