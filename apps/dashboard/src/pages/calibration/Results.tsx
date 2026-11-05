import { useState, useReducer } from 'react';
import { useDashboard, errorMessage } from '../../dashboard';
import { fmt, date } from '../../components/common';
import type { Status } from '../../types';
import type { Action } from '../Calibration';
export default function Results({ action }: { action: Action }) {
	const { status, selections, read, mutate, announce } = useDashboard(),
		selected = selections.results;
	const [, redraw] = useReducer((n) => n + 1, 0),
		[applying, setApplying] = useState(false),
		[feedback, setFeedback] = useState(''),
		[error, setError] = useState('');
	const sessions = status.calibration.cameras,
		passing = (id: string) => sessions[id]?.fit?.accepted && sessions[id]?.holdout?.accepted;
	return (
		<>
			<section className="panel">
				<h2>Results</h2>
				<div className="table-scroll">
					<table>
						<thead>
							<tr>
								<th>Camera</th>
								<th>Fit RMS</th>
								<th>Validation RMS</th>
								<th>Fit / validation views</th>
								<th>Result</th>
							</tr>
						</thead>
						<tbody>
							{Object.entries(sessions).length ? (
								Object.entries(sessions).map(([id, s]) => (
									<tr key={id}>
										<td>
											<label>
												<input
													type="checkbox"
													checked={selected.has(id)}
													onChange={(e) => {
														e.target.checked ? selected.add(id) : selected.delete(id);
														redraw();
													}}
												/>{' '}
												{status.cameras.find((c) => c.identity === id)?.name || id.slice(0, 8)}
											</label>
										</td>
										<td>{fmt(s.fit?.rms_reprojection_error_px, 2)} px</td>
										<td>{fmt(s.holdout?.rms_px, 2)} px</td>
										<td>
											{s.fit_views} / {s.holdout_views}
										</td>
										<td className={passing(id) ? 'good' : 'warning'}>
											{passing(id) ? '✓ Pass' : s.reason || s.fit?.reason || 'Capture required'}
										</td>
									</tr>
								))
							) : (
								<tr>
									<td colSpan={5}>Select cameras on Capture</td>
								</tr>
							)}
						</tbody>
					</table>
				</div>
				<div className="results-actions">
					<button
						onClick={() => {
							selected.clear();
							for (const id of Object.keys(sessions)) if (passing(id)) selected.add(id);
							redraw();
						}}
					>
						Select passing
					</button>
					<button
						className="primary"
						disabled={Boolean(
							status.lock_reason ||
							applying ||
							!selected.size ||
							[...selected].some((id) => !passing(id) || sessions[id]?.solving),
						)}
						onClick={async () => {
							setApplying(true);
							setFeedback('Applying calibration…');
							const result = await action('apply', { identities: [...selected] });
							setApplying(false);
							if (result) setFeedback('Applied · ' + result.applied_generation);
						}}
					>
						Apply selected
					</button>
					<small id="apply-status">{feedback}</small>
				</div>
			</section>
			<section className="panel history-panel">
				<h2>History</h2>
				{(status.history ?? []).filter((h) => h.cameras?.length || h.error).length ? (
					(status.history ?? [])
						.filter((h) => h.cameras?.length || h.error)
						.map((h) => (
							<HistoryEntry
								key={h.generation}
								entry={h}
								onRestore={async (ids) => {
									try {
										await mutate('configuration/restore', {
											generation: h.generation,
											calibration_ids: ids,
											revision: read().revision,
										});
										announce('Selected calibration group restored');
									} catch (e) {
										setError(errorMessage(e));
									}
								}}
							/>
						))
				) : (
					<p className="muted">No activated calibration history</p>
				)}
				<p className="feedback">{error}</p>
			</section>
		</>
	);
}
function HistoryEntry({
	entry: h,
	onRestore,
}: {
	entry: NonNullable<Status['history']>[number];
	onRestore: (ids: string[]) => Promise<void>;
}) {
	const { status, selections } = useDashboard(),
		[, redraw] = useReducer((n) => n + 1, 0);
	const [selected] = useState(() => selections.history.get(h.generation) ?? new Set<string>());
	return (
		<div className="spaced">
			<strong>{h.generation.slice(0, 12)}</strong> {h.active ? '· active' : ''}
			<p>
				{h.cameras.map((record) => {
					const current = status.cameras.find((c) => c.identity === record.identity),
						compatible = current?.connected && current.mode_signature === record.mode_signature;
					return (
						<label className="spaced" key={record.id}>
							<input
								type="checkbox"
								checked={selected.has(record.id)}
								disabled={Boolean(!compatible || h.active || status.lock_reason)}
								onChange={(e) => {
									e.target.checked ? selected.add(record.id) : selected.delete(record.id);
									selections.history.set(h.generation, selected);
									redraw();
								}}
							/>{' '}
							{current?.name || record.identity.slice(0, 8)} · {date(record.saved_at)}{' '}
							{compatible ? '' : '· current mode unavailable or incompatible'}
							<br />
						</label>
					);
				})}
			</p>
			{h.error ? (
				<span className="warning">{h.error}</span>
			) : (
				<button
					disabled={Boolean(h.active || status.lock_reason || !selected.size)}
					onClick={() => void onRestore([...selected])}
				>
					Restore selected
				</button>
			)}
		</div>
	);
}
