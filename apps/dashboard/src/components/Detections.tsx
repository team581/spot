import { useStatus } from '../queries';
import { usePreview, previewData, currentFrame } from './Feed';
import { fmt } from './common';
import type { Camera } from '../types';
export function Detections({ camera: c }: { camera: Camera }) {
	const status = useStatus(),
		view = usePreview(c.identity),
		data = previewData(view),
		fresh = currentFrame(view, c, status);
	const tags = fresh ? (data?.tags ?? []) : [],
		candidates = fresh ? (data?.candidates ?? []) : [],
		decision = status.robot_decisions?.[c.logical_name ?? ''];
	return (
		<section className="panel">
			<h2>Detections</h2>
			<p id="pose-state" role="status">
				{!c.calibrated
					? 'Pose unavailable: calibrate this camera. Tags can be detected without a calibration, but distance and pose need valid intrinsics.'
					: !fresh
						? 'Waiting for a current detection frame before showing a pose.'
						: candidates.length
							? 'Local camera pose available. Robot acceptance is checked separately.'
							: 'No pose solved for this frame. Check tag visibility, the field layout and solver diagnostics.'}
			</p>
			<div className="table-scroll">
				<table>
					<thead>
						<tr>
							<th>ID</th>
							<th>Range</th>
							<th>Error</th>
							<th>Used</th>
						</tr>
					</thead>
					<tbody id="detections">
						{tags.length ? (
							tags.map((tag) => (
								<tr key={tag.id}>
									<td>{tag.id}</td>
									<td>{tag.distance_m != null ? fmt(tag.distance_m) + ' m' : '—'}</td>
									<td>{tag.error_px != null ? fmt(tag.error_px, 2) + ' px' : '—'}</td>
									<td title={tag.reason}>{tag.used ? '✓' : '—'}</td>
								</tr>
							))
						) : (
							<tr>
								<td colSpan={4}>{fresh ? 'No tags in this frame' : 'Waiting for current detection frame'}</td>
							</tr>
						)}
					</tbody>
				</table>
			</div>
			<div id="robot-decision">
				{decision && decision.capture_epoch === data?.capture_epoch && decision.sequence === data?.sequence
					? `Robot: ${decision.state} · fusion ${decision.fusion_enabled ? 'enabled' : 'off'} · frame ${decision.fused ? 'fused' : 'not fused'}`
					: 'Robot decision unavailable for this frame'}
			</div>
			<details className="spaced">
				<summary>Solver candidates</summary>
				<pre>{JSON.stringify(candidates, null, 2)}</pre>
			</details>
		</section>
	);
}
