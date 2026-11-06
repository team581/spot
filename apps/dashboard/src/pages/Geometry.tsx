import { Link } from '@tanstack/react-router';
import { useEffect, useReducer, useState } from 'react';
import { useDashboard } from '../dashboard';
import { api, submit } from '../api';
import { readStatus, useStatus, useTask } from '../queries';
import { NumberEdit } from '../state/editing';
import GeometryViewer from '../components/GeometryViewer';
import { geometryValues, previewGeometry } from '../state/geometry';
import { CameraSelector, CameraTabs, Feedback, PageTitle, Panel, fmt } from '../components/common';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import type { Camera } from '../types';
const labels = ['X', 'Y', 'Z', 'Yaw', 'Pitch', 'Roll'];
export default function GeometryPage({ camera: c }: { camera: Camera }) {
	const { announce } = useDashboard(),
		status = useStatus(),
		task = useTask(),
		busy = task.isPending,
		[inspection, setInspection] = useState(false),
		[, redraw] = useReducer((n) => n + 1, 0);
	const [edits] = useState(() => {
		const values = c.geometry ? geometryValues(c.geometry) : [0, 0, 0, 0, 0, 0];
		return values.map((value, index) => {
			const edit = new NumberEdit(value, {
				min: index < 3 ? -10 : -180,
				max: index < 3 ? 10 : 180,
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
	const apply = () =>
		task.mutate(async () => {
			const expected = readStatus().revision;
			const document = await api<{
				cameras: { name: string; robot_to_camera: Record<string, number> }[];
				processing: unknown;
			}>('/api/robot/configuration');
			const camera = document.cameras.find((camera) => camera.name === c.logical_name);
			if (!camera || !geometry) throw new Error('Choose a configured robot camera');
			const [x_m, y_m, z_m, yaw_deg, pitch_deg, roll_deg] = values;
			camera.robot_to_camera = { x_m, y_m, z_m, roll_deg, pitch_deg, yaw_deg };
			await submit('configuration/apply', { document, revision: expected });
			setInspection(false);
			announce('Mount saved on Spot.');
		});
	return (
		<>
			<PageTitle>{c.name}</PageTitle>
			<CameraSelector cameras={status.cameras} id={c.identity} geometry />
			<CameraTabs id={c.identity} />
			<div className="grid items-start gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
				<Panel title="Mount">
					<p className="text-muted-foreground">Robot code value, including any change saved on Spot</p>
					<Label className="text-warning">
						<Checkbox checked={inspection} onCheckedChange={setInspection} /> Inspection preview
					</Label>
					<div id="geometry-fields" className="flex flex-col gap-3">
						{edits.map((edit, i) => (
							<div key={labels[i]} className="grid grid-cols-[2.25rem_minmax(0,1fr)] items-center gap-y-1">
								<Label htmlFor={'geometry-' + i}>{labels[i]}</Label>
								<div className="flex h-9 min-w-0 items-center rounded-md border border-input bg-input/20 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/30 has-disabled:opacity-50 dark:bg-input/30">
									<input
										className="w-full min-w-0 bg-transparent px-3 text-base outline-none"
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
									<span className="mr-1 text-muted-foreground">{i < 3 ? 'm' : '°'}</span>
									<span className="flex flex-col">
										{[1, -1].map((direction) => (
											<Button
												key={direction}
												variant="ghost"
												size="icon-xs"
												className="h-4"
												disabled={!inspection || !c.geometry}
												aria-label={(direction === 1 ? 'Increase ' : 'Decrease ') + labels[i]}
												onClick={(e) => {
													if (edit.step(direction, e, i >= 3)) void edit.commit().then(() => redraw());
												}}
											>
												{direction === 1 ? <ChevronUp /> : <ChevronDown />}
											</Button>
										))}
									</span>
								</div>
								<Feedback className="col-start-2">{edit.error}</Feedback>
							</div>
						))}
					</div>
					<Button variant="outline" onClick={reset}>
						Reset preview
					</Button>
					<Button disabled={busy || !inspection || !c.logical_name} onClick={() => apply()}>
						Save mount on Spot
					</Button>
					<Feedback>{busy ? 'Waiting for robot acknowledgement…' : task.error?.message}</Feedback>
					<small className="text-muted-foreground">
						0.01 m / 1°. Shift: coarse. Alt: fine. WPILib pitch: positive points down; negative points up.
					</small>
					<p>
						<Link to="/help/$" params={{ _splat: 'operator/cameras/' }} hash="geometry">
							Measuring camera geometry
						</Link>
					</p>
				</Panel>
				<div className="flex min-w-0 flex-col gap-4">
					<GeometryViewer camera={c} inspection geometry={geometry} />
					<div id="transform-readout">
						{edits.map((e, i) => `${labels[i]} ${fmt(e.previewValue, i < 3 ? 3 : 1)} ${i < 3 ? 'm' : '°'}`).join(' · ')}
					</div>
				</div>
			</div>
		</>
	);
}
