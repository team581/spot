import type { OperationName, OperationPayload } from '../api';
import { lazy, Suspense, useState } from 'react';
import { useDashboard, errorMessage } from '../dashboard';
import { CameraSelector, CameraTabs, Icon, WarningLink, age } from '../components/common';
import { Feed, usePreview, previewData, frameAge } from '../components/Feed';
import { Detections } from '../components/Detections';
import { useTuner } from '../components/useTuner';
import type { Camera } from '../types';
import { TuningControl } from '../components/TuningControl';
const GeometryViewer = lazy(() => import('../components/GeometryViewer'));
export default function CameraDetail({ camera }: { camera: Camera }) {
	const [version, setVersion] = useState(0);
	return <CameraDetailPage key={version} camera={camera} onModeApplied={() => setVersion((value) => value + 1)} />;
}
function CameraDetailPage({ camera: c, onModeApplied }: { camera: Camera; onModeApplied: () => void }) {
	const { status, mutate, announce, previews } = useDashboard(),
		{ tuner, history, reset, reconcile } = useTuner(c);
	const [error, setError] = useState(''),
		[outlines, setOutlines] = useState(true),
		[code, setCode] = useState(''),
		[replacement, setReplacement] = useState(''),
		[confirmed, setConfirmed] = useState(false);
	const view = usePreview(c.identity),
		data = previewData(view),
		preferred = ['exposure_time_absolute', 'exposure_absolute', 'gain', 'brightness'];
	const primary = (c.controls ?? [])
			.filter((v) => preferred.includes(v.name))
			.sort((a, b) => preferred.indexOf(a.name) - preferred.indexOf(b.name)),
		advanced = (c.controls ?? []).filter((v) => !preferred.includes(v.name));
	const replacements = status.cameras.filter(
		(cam) => cam.connected && (!cam.logical_name || cam.identity === c.identity),
	);
	const replacementId = replacements.some((cam) => cam.identity === replacement)
		? replacement
		: (replacements[0]?.identity ?? '');
	const run = async <N extends OperationName>(operation: N, payload: OperationPayload<N>) => {
		try {
			return await mutate(operation, payload);
		} catch (e) {
			setError(errorMessage(e));
			announce(errorMessage(e));
			return null;
		}
	};
	const target = c.logical_name ? { name: c.logical_name } : { identity: c.identity };
	return (
		<>
			{!c.logical_name ? (
				<div className="panel warning">
					<strong>Not configured with the robot.</strong> Standalone tuning and calibration; the 3D camera is at (0, 0,
					0), with zero rotation.{' '}
					<button onClick={() => void run('device/setup', { identity: c.identity, revision: status.revision })}>
						Enable standalone setup
					</button>
				</div>
			) : null}
			<div className="page-heading">
				<h1 id="camera-title">{c.name}</h1>
				<span id="calibrated-state">
					<WarningLink camera={c} />
				</span>
			</div>
			<CameraSelector cameras={status.cameras} id={c.identity} />
			<CameraTabs id={c.identity} />
			<div className="camera-layout">
				<section className="panel config-panel">
					<div className="panel-heading">
						<h2>Config</h2>
						<span className="history-buttons">
							{(['undo', 'redo'] as const).map((direction) => {
								const stack = direction === 'undo' ? tuner.history.undoStack : tuner.history.redoStack;
								return (
									<button
										key={direction}
										className="icon-button"
										aria-label={direction === 'undo' ? 'Undo' : 'Redo'}
										disabled={Boolean(
											!stack.length ||
											status.lock_reason ||
											tuner.inFlight ||
											tuner.pending ||
											tuner.gesture ||
											tuner.history.conflict,
										)}
										onClick={() => void history(direction)}
									>
										<Icon name={direction} />
									</button>
								);
							})}
						</span>
					</div>
					<p id="config-lock" className="lock">
						{status.lock_reason}
					</p>
					{primary.map((ctrl) => (
						<TuningControl key={ctrl.name} control={ctrl} tuner={tuner} camera={c} />
					))}
					<div className="mode-control">
						<label htmlFor="optical-mode">Capture resolution / rate</label>
						<select
							id="optical-mode"
							value={c.mode_id || ''}
							disabled={Boolean(status.lock_reason || !c.connected || tuner.inFlight)}
							onChange={(e) =>
								void run(c.logical_name ? 'mode' : 'device/mode', {
									...target,
									mode_id: e.target.value,
									revision: status.revision,
								}).then((result) => {
									if (result) onModeApplied();
								})
							}
						>
							{(c.allowed_modes ?? []).map((m) => (
								<option key={m.id} value={m.id} disabled={!m.supported}>
									{m.width} × {m.height} · {m.fps} FPS · {m.pixel_format}
									{m.supported ? '' : ' · unsupported'}
								</option>
							))}
						</select>
					</div>
					<div id="control-feedback" className="feedback">
						{tuner.error || (tuner.inFlight || tuner.pending ? 'Pending device acknowledgement' : '')}
					</div>
					<button
						className="reset"
						disabled={Boolean(
							status.lock_reason ||
							!(c.controls ?? []).some((ctrl) => ctrl.allowed) ||
							tuner.inFlight ||
							tuner.history.conflict,
						)}
						onClick={() => void reset()}
					>
						{c.logical_name ? 'Reset to code defaults' : 'Reset setup values'}
					</button>
					<details>
						<summary>Advanced</summary>
						{advanced.map((ctrl) => (
							<TuningControl key={ctrl.name} control={ctrl} tuner={tuner} camera={c} />
						))}
						<button
							className="spaced"
							onClick={async () => {
								const value = (c.controls ?? [])
									.map(
										(ctrl) =>
											`VisionProfiles.${ctrl.allowed ? 'tuning' : 'pinned'}("${ctrl.name}", ${ctrl.value}${ctrl.allowed ? '' : ', ' + Boolean(ctrl.required)})`,
									)
									.join(',\n');
								setCode(value);
								try {
									await navigator.clipboard.writeText(value);
									announce('Settings copied as code');
								} catch {
									announce('Code displayed for copying');
								}
							}}
						>
							Copy settings as code
						</button>
						{code ? <pre>{code}</pre> : null}
						<label className="spaced" htmlFor="replacement-identity">
							Replacement camera
						</label>
						<select id="replacement-identity" value={replacementId} onChange={(e) => setReplacement(e.target.value)}>
							{replacements.map((cam) => (
								<option key={cam.identity} value={cam.identity}>
									{cam.name} · {cam.display_id || ''}
								</option>
							))}
						</select>
						<label className="spaced">
							<input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> I confirmed
							the replacement feed
						</label>
						<button
							className="spaced"
							disabled={Boolean(!c.logical_name || status.lock_reason || !replacements.length)}
							onClick={() => {
								if (!c.logical_name) return;
								if (!confirmed) {
									setError('Identify the replacement feed before replacing this camera');
									return;
								}
								void run('replace', {
									name: c.logical_name,
									identity: replacementId,
									revision: status.revision,
								}).then((result) => {
									if (result) announce('Physical camera calibration invalidated');
								});
							}}
						>
							Replace camera
						</button>
					</details>
					{tuner.history.conflict ? (
						<button className="spaced" onClick={() => void reconcile()}>
							Reconcile current values
						</button>
					) : null}
					<p id="page-feedback" className="feedback">
						{error}
					</p>
					<a href="/docs/operator/cameras/#tune">Tuning and history</a>
				</section>
				<div>
					<Feed id={c.identity} outlines={outlines} />
					<div className="feed-controls">
						<label>
							<input type="checkbox" checked={outlines} onChange={(e) => setOutlines(e.target.checked)} />
							Show detection outlines
						</label>
						<button onClick={() => previews.toggle(c.identity, status)}>
							{view.paused ? 'Resume image' : 'Pause image'}
						</button>
						<small id="frame-info">
							{data
								? `Frame ${data.sequence} · ${age(frameAge(view))} · ${data.width} × ${data.height}`
								: 'Waiting for frame'}
						</small>
					</div>
					<div className="detail-bottom">
						<Detections camera={c} />
						<Suspense fallback={<p>Loading geometry…</p>}>
							<GeometryViewer camera={c} />
						</Suspense>
					</div>
				</div>
			</div>
		</>
	);
}
