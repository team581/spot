import { Link } from '@tanstack/react-router';
import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Feed } from '../../components/Feed';
import { Steps, type Step } from '../../components/Steps';
import { readStatus, useOperation, useStatus } from '../../queries';
import type { CalibrationOperation } from '../Calibration';
import { Panel, fmt } from '../../components/common';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Progress } from '@/components/ui/progress';
// OpenCV's predefined ArUco dictionaries used for ChArUco boards.
const dictionaries = [4, 5, 6, 7].flatMap((bits) => [50, 100, 250, 1000].map((n) => `DICT_${bits}X${bits}_${n}`));
const boardLabels: Record<string, string> = {
	dictionary: 'Dictionary',
	squares_x: 'Squares X',
	squares_y: 'Squares Y',
	square_length_m: 'Square length (m)',
	marker_length_m: 'Marker length (m)',
};
// Matches the backend's independent validation minimum.
const minValidationViews = 5;
export default function Capture({ operation }: { operation: CalibrationOperation }) {
	const status = useStatus(),
		[board, setBoard] = useState(status.calibration.board ?? {}),
		id = Object.keys(status.calibration.cameras)[0] ?? '';
	const select = (identity: string) =>
		operation.mutateAsync({
			operation: 'calibration/select',
			payload: { identities: identity ? [identity] : [], revision: readStatus().revision },
		});
	return (
		<div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
			<div className="flex flex-col gap-4">
				<Label className="flex-col items-stretch sm:max-w-xs">
					Camera
					<NativeSelect
						aria-label="Camera"
						className="w-full"
						value={id}
						onChange={(e) => void select(e.target.value).catch(() => {})}
					>
						<NativeSelectOption value="">Choose a camera</NativeSelectOption>
						{status.cameras
							.filter((c) => c.logical_name)
							.map((c) => (
								<NativeSelectOption value={c.identity} key={c.identity}>
									{c.name}
								</NativeSelectOption>
							))}
					</NativeSelect>
				</Label>
				{id ? (
					<CameraCalibration key={id} id={id} operation={operation} />
				) : (
					<p className="text-muted-foreground">Choose a named camera to calibrate.</p>
				)}
			</div>
			<Panel title="Board" className="max-lg:order-first">
				<p className="text-xs text-muted-foreground">Match the board you are showing the camera.</p>
				<div className="grid gap-3 max-lg:grid-cols-2">
					{Object.entries(boardLabels).map(([key, label]) => (
						<Label key={key} className="flex-col items-stretch">
							{label}
							{key === 'dictionary' ? (
								<NativeSelect
									className="w-full"
									value={board[key] ?? ''}
									onChange={(e) => setBoard({ ...board, [key]: e.target.value })}
								>
									{[...new Set([...dictionaries, String(board[key] ?? '')])].filter(Boolean).map((name) => (
										<NativeSelectOption value={name} key={name}>
											{name}
										</NativeSelectOption>
									))}
								</NativeSelect>
							) : (
								<Input
									type="number"
									{...(key.startsWith('squares') ? { min: 2, max: 40, step: 1 } : { min: 0, step: 0.0005 })}
									value={board[key] ?? ''}
									onChange={(e) => setBoard({ ...board, [key]: e.target.value })}
								/>
							)}
						</Label>
					))}
				</div>
				<BoardPreview board={board} />
				<Button
					variant="outline"
					onClick={async () => {
						const values = Object.fromEntries(
							Object.keys(status.calibration.board ?? {}).map((key) => [
								key,
								key === 'dictionary' ? board[key] : Number(board[key]),
							]),
						);
						try {
							await operation.mutateAsync({
								operation: 'calibration/board',
								payload: { board: values, options: { ...status.calibration.options }, revision: readStatus().revision },
							});
							// Changing the board clears the session, so reselect the camera.
							if (id) await select(id);
						} catch {
							// The page shows the operation error.
						}
					}}
				>
					Update board
				</Button>
				<p>
					<Link to="/help/$" params={{ _splat: 'operator/cameras/' }} hash="calibrate">
						Calibration guide
					</Link>
				</p>
			</Panel>
		</div>
	);
}
function CameraCalibration({ id, operation }: { id: string; operation: CalibrationOperation }) {
	const status = useStatus(),
		apply = useOperation<'calibration/apply'>(),
		session = status.calibration.cameras[id]!,
		minFitViews = Number(status.calibration.options?.min_frames) || 15,
		fitted = Boolean(session.fit?.accepted),
		validated = Boolean(session.holdout?.accepted),
		phase = fitted ? 'holdout' : 'fit',
		capturing = session.running && session.phase === phase,
		views = fitted ? session.holdout_views : session.fit_views,
		needed = fitted ? minValidationViews : minFitViews;
	const run = (action: string) =>
		operation.mutate({
			operation: `calibration/${action}` as 'calibration/start',
			payload: { identity: id, phase, automatic: true, revision: readStatus().revision },
		});
	const steps: Step[] = [
		{
			label: 'Capture fitting views',
			detail: `${session.fit_views} / ${minFitViews} views`,
			state: fitted || session.fit_views >= minFitViews ? 'complete' : 'current',
		},
		{
			label: 'Calibrate',
			detail: session.fit ? `${fmt(session.fit.rms_reprojection_error_px, 2)} px RMS` : undefined,
			state: fitted ? 'complete' : session.fit ? 'warning' : session.fit_views >= minFitViews ? 'current' : 'upcoming',
		},
		{
			label: 'Capture validation views',
			detail: fitted ? `${session.holdout_views} / ${minValidationViews} views` : undefined,
			state: !fitted ? 'upcoming' : validated || session.holdout_views >= minValidationViews ? 'complete' : 'current',
		},
		{
			label: 'Validate',
			detail: session.holdout ? `${fmt(session.holdout.rms_px, 2)} px RMS` : undefined,
			state: validated ? 'complete' : session.holdout ? 'warning' : fitted ? 'current' : 'upcoming',
		},
	];
	const message = session.solving
		? fitted
			? 'Validating…'
			: 'Calibrating…'
		: validated
			? 'Calibration passed. Apply it to save it for this camera.'
			: capturing
				? session.reason || 'Show the board'
				: session.holdout && !session.holdout.accepted
					? `Validation failed: ${session.holdout.reason || 'retry'}. Capture more validation views and validate again.`
					: session.fit && !session.fit.accepted
						? `Calibration failed: ${session.fit.reason || 'retry'}. Capture more fitting views and calibrate again.`
						: `Capture is paused. Click Start capture, then move the board around the whole image.`;
	return (
		<>
			<Steps steps={steps} />
			<div className="flex flex-col gap-2">
				<div className="flex items-center gap-2 text-sm">
					<span
						className={capturing ? 'size-2.5 animate-pulse rounded-full bg-success' : 'size-2.5 rounded-full bg-border'}
					/>
					<strong>{capturing ? `Capturing ${fitted ? 'validation' : 'fitting'} views` : 'Paused'}</strong>
					<span className="text-muted-foreground">
						{views} / {needed} views
						{fitted ? '' : ` · ${Math.round((session.coverage?.coverage_progress || 0) * 100)}% coverage`}
					</span>
				</div>
				{fitted ? null : (
					<Progress
						value={Math.max(0, Math.min(100, (session.coverage?.coverage_progress || 0) * 100))}
						aria-label="Calibration coverage"
					/>
				)}
				<p id="capture-status" role="status" className="text-sm">
					{message}
				</p>
			</div>
			<div className="flex flex-wrap gap-2">
				{validated ? (
					<Button
						disabled={apply.isPending || session.solving}
						onClick={() =>
							apply.mutate({
								operation: 'calibration/apply',
								payload: { identities: [id], revision: readStatus().revision },
							})
						}
					>
						Apply calibration
					</Button>
				) : (
					<>
						<Button
							variant={capturing ? 'outline' : 'default'}
							disabled={session.solving}
							onClick={() => run(capturing ? 'pause' : 'start')}
						>
							{capturing ? 'Pause capture' : 'Start capture'}
						</Button>
						<Button
							variant={views >= needed && !capturing ? 'default' : 'outline'}
							disabled={session.solving || views < needed}
							onClick={() => run(fitted ? 'validate' : 'compute')}
						>
							{fitted ? 'Validate' : 'Calibrate'}
						</Button>
					</>
				)}
				<Button variant="outline" disabled={session.solving || views === 0} onClick={() => run('clear')}>
					Clear {fitted ? 'validation' : 'fitting'} views
				</Button>
				<small id="apply-status" className="self-center text-muted-foreground">
					{apply.isPending
						? 'Applying calibration…'
						: apply.isSuccess
							? 'Applied · ' + apply.data.applied_generation
							: apply.error?.message}
				</small>
			</div>
			<Feed id={id} calibration className="aspect-[1.6]" />
		</>
	);
}
/** Draws the board from the entered values so operators can compare it with their print. */
function BoardPreview({ board }: { board: Record<string, string | number> }) {
	const params = new URLSearchParams(
		Object.keys(boardLabels).map((key) => [key, String(board[key] ?? '').trim()]),
	).toString();
	const preview = useQuery({
		queryKey: ['board-preview', params],
		queryFn: async () => {
			const blob = await api<Blob>(`/api/calibration/board.png?${params}`, {
				parseResponse: (response) => response.blob(),
			});
			return new Promise<string>((resolve) => {
				const reader = new FileReader();
				reader.onload = () => resolve(reader.result as string);
				reader.readAsDataURL(blob);
			});
		},
		placeholderData: keepPreviousData,
		retry: false,
		staleTime: Infinity,
	});
	const width = Number(board.squares_x) * Number(board.square_length_m) * 1000,
		height = Number(board.squares_y) * Number(board.square_length_m) * 1000;
	return (
		<figure className="flex flex-col gap-1.5">
			{preview.data && !preview.isError ? (
				<img src={preview.data} alt="Board preview" className="w-full border" />
			) : null}
			<figcaption className="text-xs text-muted-foreground">
				{preview.isError
					? `Can't draw this board: ${preview.error.message}`
					: `Expected board: ${fmt(width, 0)} × ${fmt(height, 0)} mm. Check that its pattern matches yours, including which corner the first marker is in.`}
			</figcaption>
		</figure>
	);
}
