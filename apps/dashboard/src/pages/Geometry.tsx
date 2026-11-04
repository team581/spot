import { useEffect, useReducer, useState } from 'react';
import { useDashboard } from '../dashboard';
import { NumberEdit } from '../state/editing';
import GeometryViewer from '../components/GeometryViewer';
import { geometryValues, previewGeometry } from '../state/geometry';
import { CameraSelector, CameraTabs, fmt, Icon } from '../components/common';
import type { Camera } from '../types';
const labels = ['X', 'Y', 'Z', 'Yaw', 'Pitch', 'Roll'];
export default function GeometryPage({ camera: c }: { camera: Camera }) {
	const { status } = useDashboard(),
		[inspection, setInspection] = useState(false),
		[, redraw] = useReducer((n) => n + 1, 0);
	const [edits] = useState(() => {
		const values = c.geometry ? geometryValues(c.geometry) : [0, 0, 0, 0, 0, 0];
		return values.map((value, index) => {
			const edit = new NumberEdit(value, {
				min: index < 3 ? -10 : -360,
				max: index < 3 ? 10 : 360,
				revision: status.revision,
				preview: (value) => {
					edit.previewValue = value;
					redraw();
				},
				commit: async (value) => ({ value, revision: edit.revision }),
			});
			edit.previewValue = value;
			return edit;
		});
	});
	useEffect(() => {
		if (!c.geometry) return;
		const values = geometryValues(c.geometry);
		edits.forEach((edit, i) => {
			if (!inspection || edit.revision !== status.revision) edit.readback(values[i], status.revision);
		});
		redraw();
	}, [c.geometry, status.revision, inspection, edits]);
	const values = edits.map((e) => (Number.isFinite(e.previewValue) ? e.previewValue : e.ack));
	const geometry = c.geometry ? previewGeometry(values) : null;
	const reset = () => {
		if (!c.geometry) return;
		const defaults = geometryValues(c.geometry);
		edits.forEach((edit, i) => {
			edit.ack = defaults[i];
			edit.previewValue = defaults[i];
			edit.cancel();
		});
		redraw();
	};
	return (
		<>
			<h1>{c.name}</h1>
			<CameraSelector cameras={status.cameras} id={c.identity} geometry />
			<CameraTabs id={c.identity} geometry />
			<div className="camera-layout">
				<section className="panel geometry-panel">
					<div className="panel-heading">
						<h2>Geometry</h2>
						<span className="history-buttons">
							{['undo', 'redo'].map((direction) => (
								<button
									key={direction}
									className="icon-button"
									aria-label={direction === 'undo' ? 'Undo' : 'Redo'}
									disabled
								>
									<Icon name={direction} />
								</button>
							))}
						</span>
					</div>
					<p className="lock">
						{c.logical_name ? 'Transform pinned by robot code' : 'Not configured with the robot · local origin only'}
					</p>
					<label className="inspection">
						<input type="checkbox" checked={inspection} onChange={(e) => setInspection(e.target.checked)} /> Inspection
						preview
					</label>
					<div id="geometry-fields">
						{edits.map((edit, i) => (
							<div key={labels[i]} className="number-field">
								<label htmlFor={'geometry-' + i}>{labels[i]}</label>
								<div className="number-box">
									<input
										id={'geometry-' + i}
										type="text"
										inputMode="decimal"
										autoComplete="off"
										aria-label={labels[i]}
										disabled={!inspection || !c.geometry}
										value={c.geometry ? edit.text : ''}
										onFocus={() => edit.focus()}
										onChange={(e) => {
											edit.input(e.target.value);
											redraw();
										}}
										onBlur={() => {
											edit.focused = false;
											void edit.commit().then(() => redraw());
										}}
										onKeyDown={(e) => {
											if (e.key === 'Escape') {
												edit.cancel();
												redraw();
											} else if (e.key === 'Enter') {
												e.preventDefault();
												void edit.commit().then(() => redraw());
											} else if (['ArrowUp', 'ArrowDown'].includes(e.key)) {
												e.preventDefault();
												if (edit.step(e.key === 'ArrowUp' ? 1 : -1, e, i >= 3)) void edit.commit().then(() => redraw());
											}
										}}
									/>
									<span className="unit">{i < 3 ? 'm' : '°'}</span>
									<span className="steppers">
										{[1, -1].map((direction) => (
											<button
												key={direction}
												disabled={!inspection || !c.geometry}
												aria-label={(direction === 1 ? 'Increase ' : 'Decrease ') + labels[i]}
												onClick={(e) => {
													if (edit.step(direction, e, i >= 3)) void edit.commit().then(() => redraw());
												}}
											>
												{direction === 1 ? '▴' : '▾'}
											</button>
										))}
									</span>
								</div>
								<span className="feedback">{edit.error}</span>
							</div>
						))}
					</div>
					<button className="reset" onClick={reset}>
						Reset to code defaults
					</button>
					<small>0.01 m / 1°. Shift: coarse. Alt: fine. WPILib pitch: positive points down; negative points up.</small>
					<p>
						<a href="/docs/operator/geometry/">Measuring camera geometry</a>
					</p>
				</section>
				<div>
					<GeometryViewer camera={c} inspection geometry={geometry} />
					<div className="transform-readout" id="transform-readout">
						{edits.map((e, i) => `${labels[i]} ${fmt(e.previewValue, i < 3 ? 3 : 1)} ${i < 3 ? 'm' : '°'}`).join(' · ')}
					</div>
				</div>
			</div>
		</>
	);
}
