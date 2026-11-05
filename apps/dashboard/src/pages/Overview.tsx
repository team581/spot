import { useDashboard } from '../dashboard';
import { Feed, usePreview } from '../components/Feed';
import { age } from '../components/common';
import type { Camera } from '../types';
function Tile({ camera: c }: { camera: Camera }) {
	const view = usePreview(c.identity),
		captureFresh = c.connected && c.age_s != null && c.age_s < 0.5,
		fresh = c.connected && c.metrics?.detect_age_s != null && c.metrics.detect_age_s < 0.5;
	return (
		<a className="panel tile" href={'#camera/' + encodeURIComponent(c.identity)} data-tile={c.identity}>
			<header>
				<strong>{c.name}</strong>
				<span className={'calibrated ' + (c.calibrated ? 'good' : 'warning')}>
					{c.health === 'Disabled'
						? 'Disabled in code'
						: !c.logical_name
							? '⚠ Choose camera name'
							: c.calibrated
								? '✓ calibrated'
								: '⚠ Calibration required'}
				</span>
			</header>
			<Feed id={c.identity} />
			<div className="metrics">
				<span className="fps" title="Measured capture FPS; detection and preview rates are separate">
					{captureFresh && c.metrics?.captured && Number.isFinite(c.metrics.fps_capture)
						? `${Math.round(c.metrics.fps_capture!)} FPS`
						: '— FPS'}
				</span>
				<span className="tags">
					{view.data && !view.data.stale && fresh && view.data.processed ? `${view.data.tags.length} tags` : '— tags'}
				</span>
				<span className="age">{age(c.age_s)}</span>
			</div>
		</a>
	);
}
export default function Overview({ page }: { page: string }) {
	const { status, serviceError } = useDashboard();
	return (
		<>
			<h1>{page === 'cameras' ? 'Cameras' : 'Overview'}</h1>
			<div id="tiles" className="overview-grid">
				{status.cameras.length ? (
					status.cameras.map((c) => <Tile key={c.identity} camera={c} />)
				) : (
					<div className="panel empty">
						<h2>No cameras discovered</h2>
						<p>Connect a powered USB camera. Discovery continues automatically.</p>
						<a href="/docs/operator/cameras/#connect">Connection guide</a>
					</div>
				)}
			</div>
			<p id="page-feedback" className="feedback">
				{serviceError}
			</p>
		</>
	);
}
