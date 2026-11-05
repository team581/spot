import { lazy, Suspense, useState } from 'react';
import { Link } from '@tanstack/react-router';
import { useDashboard } from '../dashboard';
import { useOperation, useStatus } from '../queries';
import { CalibrationState, CameraSelector, CameraTabs, Feedback, Panel, PageTitle, age } from '../components/common';
import { Redo2, TriangleAlert, Undo2 } from 'lucide-react';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
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
	const { announce, previews } = useDashboard(),
		status = useStatus(),
		operation = useOperation(),
		{ tuner, history, reset, reconcile } = useTuner(c);
	const [notice, setNotice] = useState(''),
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
	return (
		<>
			{!c.logical_name ? (
				<Alert>
					<TriangleAlert />
					<AlertTitle>Not configured with the robot.</AlertTitle>
					<AlertDescription>
						Standalone tuning and calibration; the 3D camera is at (0, 0, 0), with zero rotation.
					</AlertDescription>
					<AlertAction>
						<Button
							size="sm"
							onClick={() =>
								operation.mutate({
									operation: 'device/setup',
									payload: { identity: c.identity, revision: status.revision },
								})
							}
						>
							Enable standalone setup
						</Button>
					</AlertAction>
				</Alert>
			) : null}
			<div className="flex items-center justify-between gap-4">
				<PageTitle id="camera-title">{c.name}</PageTitle>
				<Link id="calibrated-state" to="/calibration">
					<CalibrationState camera={c} />
				</Link>
			</div>
			<CameraSelector cameras={status.cameras} id={c.identity} />
			<CameraTabs id={c.identity} />
			<div className="grid items-start gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
				<Panel
					title="Config"
					action={
						<span className="flex">
							{(['undo', 'redo'] as const).map((direction) => {
								const stack = direction === 'undo' ? tuner.history.undoStack : tuner.history.redoStack;
								return (
									<Button
										key={direction}
										variant="ghost"
										size="icon"
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
										{direction === 'undo' ? <Undo2 /> : <Redo2 />}
									</Button>
								);
							})}
						</span>
					}
				>
					<Feedback id="config-lock">{status.lock_reason}</Feedback>
					{primary.map((ctrl) => (
						<TuningControl key={ctrl.name} control={ctrl} tuner={tuner} camera={c} />
					))}
					<div className="flex flex-col gap-2">
						<Label htmlFor="optical-mode">Capture resolution / rate</Label>
						<NativeSelect
							id="optical-mode"
							className="w-full"
							value={c.mode_id || ''}
							disabled={Boolean(status.lock_reason || !c.connected || tuner.inFlight)}
							onChange={(e) => {
								const mode = { mode_id: e.target.value, revision: status.revision };
								operation.mutate(
									c.logical_name
										? { operation: 'camera/mode', payload: { name: c.logical_name, ...mode } }
										: { operation: 'device/mode', payload: { identity: c.identity, ...mode } },
									{ onSuccess: onModeApplied },
								);
							}}
						>
							{(c.allowed_modes ?? []).map((m) => (
								<NativeSelectOption key={m.id} value={m.id} disabled={!m.supported}>
									{m.width} × {m.height} · {m.fps} FPS · {m.pixel_format}
									{m.supported ? '' : ' · unsupported'}
								</NativeSelectOption>
							))}
						</NativeSelect>
					</div>
					<Feedback id="control-feedback">
						{tuner.error || (tuner.inFlight || tuner.pending ? 'Pending device acknowledgement' : '')}
					</Feedback>
					<Button
						variant="outline"
						disabled={Boolean(
							status.lock_reason ||
							!(c.controls ?? []).some((ctrl) => ctrl.allowed) ||
							tuner.inFlight ||
							tuner.history.conflict,
						)}
						onClick={() => void reset()}
					>
						{c.logical_name ? 'Reset to code defaults' : 'Reset setup values'}
					</Button>
					<Collapsible>
						<CollapsibleTrigger className="text-muted-foreground hover:text-foreground">Advanced</CollapsibleTrigger>
						<CollapsibleContent className="mt-3 flex flex-col gap-3">
							{advanced.map((ctrl) => (
								<TuningControl key={ctrl.name} control={ctrl} tuner={tuner} camera={c} />
							))}
							<Button
								variant="outline"
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
							</Button>
							{code ? <pre className="overflow-auto rounded-md bg-muted p-2 text-xs">{code}</pre> : null}
							<Label htmlFor="replacement-identity">Replacement camera</Label>
							<NativeSelect
								id="replacement-identity"
								className="w-full"
								value={replacementId}
								onChange={(e) => setReplacement(e.target.value)}
							>
								{replacements.map((cam) => (
									<NativeSelectOption key={cam.identity} value={cam.identity}>
										{cam.name} · {cam.display_id || ''}
									</NativeSelectOption>
								))}
							</NativeSelect>
							<Label>
								<Checkbox checked={confirmed} onCheckedChange={setConfirmed} /> I confirmed the replacement feed
							</Label>
							<Button
								variant="outline"
								disabled={Boolean(!c.logical_name || status.lock_reason || !replacements.length)}
								onClick={() => {
									if (!c.logical_name) return;
									if (!confirmed) {
										setNotice('Identify the replacement feed before replacing this camera');
										return;
									}
									setNotice('');
									operation.mutate(
										{
											operation: 'camera/replace',
											payload: { name: c.logical_name, identity: replacementId, revision: status.revision },
										},
										{ onSuccess: () => announce('Physical camera calibration invalidated') },
									);
								}}
							>
								Replace camera
							</Button>
						</CollapsibleContent>
					</Collapsible>
					{tuner.history.conflict ? (
						<Button variant="outline" onClick={() => void reconcile()}>
							Reconcile current values
						</Button>
					) : null}
					<Feedback id="page-feedback">{notice || operation.error?.message}</Feedback>
					<a href="/docs/operator/cameras/#tune">Tuning and history</a>
				</Panel>
				<div className="flex min-w-0 flex-col gap-4">
					<Feed id={c.identity} outlines={outlines} />
					<div className="flex flex-wrap items-center gap-4">
						<Label>
							<Checkbox checked={outlines} onCheckedChange={setOutlines} />
							Show detection outlines
						</Label>
						<Button variant="outline" onClick={() => previews.toggle(c.identity, status)}>
							{view.paused ? 'Resume image' : 'Pause image'}
						</Button>
						<small id="frame-info" className="ml-auto text-xs text-muted-foreground">
							{data
								? `Frame ${data.sequence} · ${age(frameAge(view))} · ${data.width} × ${data.height}`
								: 'Waiting for frame'}
						</small>
					</div>
					<div className="grid gap-4 xl:grid-cols-2">
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
