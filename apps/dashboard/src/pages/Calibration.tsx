import { useState } from 'react';
import type { Settings } from '../api';
import { $api, queryClient, useEditOverrides, useSaveSettings, useSettings, useStatus } from '../queries';
import { useCharuco, useImage } from '../live';
import { DataList, ErrorText, PageTitle, Panel } from '../components/common';
import { fmt } from '../format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type { components } from '../api.gen';

type Board = components['schemas']['Board'];
type Session = components['schemas']['CalibrationView'];
const dictionaries: Board['dictionary'][] = ['4x4_50', '4x4_100', '4x4_250', '5x5_50', '5x5_100', '6x6_50', '6x6_250'];
/** Coverage hint grid: cells with a captured corner count as covered. */
const GRID = 6;
const cameraParams = (camera: string) => ({ params: { path: { camera } } });
const sessionKey = (camera: string) =>
	$api.queryOptions('get', '/api/calibration/{camera}', cameraParams(camera)).queryKey;
const setSession = (data: Session) => queryClient.setQueryData(sessionKey(data.camera), data);

function BoardForm({ settings }: { settings: Settings }) {
	const board = settings.calibration_board;
	const [draft, setDraft] = useState({
		dictionary: board.dictionary,
		marker_mm: String(board.marker_size * 1000),
		square_mm: String(board.square_size * 1000),
		squares_x: String(board.squares_x),
		squares_y: String(board.squares_y),
	});
	const [failedPreview, setFailedPreview] = useState('');
	const save = useSaveSettings();
	const draftBoard: Board = {
		dictionary: draft.dictionary,
		marker_size: Number(draft.marker_mm) / 1000,
		square_size: Number(draft.square_mm) / 1000,
		squares_x: Number(draft.squares_x),
		squares_y: Number(draft.squares_y),
	};
	const preview = `/api/calibration/board.png?${new URLSearchParams(
		Object.entries(draftBoard).map(([key, value]) => [key, String(value)]),
	).toString()}`;
	const field = (key: 'squares_x' | 'squares_y' | 'square_mm' | 'marker_mm', label: string) => (
		<div className="flex flex-col gap-2">
			<Label htmlFor={key}>{label}</Label>
			<Input
				id={key}
				inputMode="decimal"
				value={draft[key]}
				onChange={(e) => {
					setDraft({ ...draft, [key]: e.target.value });
				}}
			/>
		</div>
	);
	return (
		<form
			className="flex flex-col gap-4"
			onSubmit={(e) => {
				e.preventDefault();
				save.mutate({ body: { ...settings, calibration_board: draftBoard } });
			}}
		>
			<div className="grid grid-cols-2 gap-3">
				{field('squares_x', 'Squares across')}
				{field('squares_y', 'Squares down')}
				{field('square_mm', 'Square size (mm)')}
				{field('marker_mm', 'Marker size (mm)')}
			</div>
			<div className="flex flex-col gap-2">
				<Label htmlFor="dictionary">Dictionary</Label>
				<NativeSelect
					id="dictionary"
					value={draft.dictionary}
					onChange={(e) => {
						const dictionary = dictionaries.find((d) => d === e.target.value);
						if (dictionary) {
							setDraft({ ...draft, dictionary });
						}
					}}
				>
					{dictionaries.map((d) => (
						<NativeSelectOption key={d} value={d}>
							{d.toUpperCase()}
						</NativeSelectOption>
					))}
				</NativeSelect>
			</div>
			{failedPreview === preview ? (
				<ErrorText error="These settings don't describe a valid board." />
			) : (
				<img
					src={preview}
					alt="Board preview"
					className="w-full rounded-md bg-white p-2"
					onError={() => {
						setFailedPreview(preview);
					}}
				/>
			)}
			<p className="text-sm text-muted-foreground">
				Enter your board's measured sizes, and check that the preview matches it before saving.
			</p>
			<Button type="submit" className="self-start" disabled={save.isPending}>
				Save board
			</Button>
			<ErrorText error={save.error} />
		</form>
	);
}

/** Live image with the detected board corners, captured corners, and coverage of the image. */
function CalibrationView({ session }: { session: Session }) {
	const image = useImage(session.camera);
	const charuco = useCharuco(session.camera);
	const width = session.width ?? charuco?.width ?? 1280;
	const height = session.height ?? charuco?.height ?? 800;
	const covered = new Set(
		session.frames.flatMap((f) =>
			f.corners.map(([x, y]) => Math.floor((x / width) * GRID) + GRID * Math.floor((y / height) * GRID)),
		),
	);
	return (
		<div className="relative overflow-hidden rounded-md bg-feed" style={{ aspectRatio: `${width} / ${height}` }}>
			{image ? <img src={image} alt="" className="absolute inset-0 size-full object-contain" /> : null}
			<svg viewBox={`0 0 ${width} ${height}`} className="absolute inset-0 size-full">
				{Array.from({ length: GRID * GRID }, (_, i) => (
					<rect
						key={i}
						x={((i % GRID) * width) / GRID}
						y={(Math.floor(i / GRID) * height) / GRID}
						width={width / GRID}
						height={height / GRID}
						fill={covered.has(i) ? 'transparent' : '#edc06c'}
						fillOpacity={0.35}
						stroke="#ffffff"
						strokeOpacity={0.15}
					/>
				))}
				{session.frames.flatMap((f, i) =>
					f.corners.map(([x, y], j) => (
						<circle key={`${i}-${f.ids[j]}`} cx={x} cy={y} r={width / 250} fill="#8ab4f8" />
					)),
				)}
				{charuco?.corners.map(([x, y], i) => (
					<circle
						key={charuco.ids[i]}
						cx={x}
						cy={y}
						r={width / 120}
						fill="none"
						stroke="#2fb36b"
						strokeWidth={3}
						vectorEffect="non-scaling-stroke"
					/>
				))}
			</svg>
		</div>
	);
}

function SessionPanel({ session }: { session: Session }) {
	const overrides = useEditOverrides();
	const capture = $api.useMutation('post', '/api/calibration/{camera}/capture', { onSuccess: setSession });
	const solve = $api.useMutation('post', '/api/calibration/{camera}/solve', { onSuccess: setSession });
	const stop = $api.useMutation('delete', '/api/calibration/{camera}', {
		onSuccess: () => {
			queryClient.removeQueries({ queryKey: sessionKey(session.camera) });
		},
	});
	const busy = capture.isPending || solve.isPending;
	const { solution } = session;
	const resolution = `${session.width}x${session.height}`;
	const enough = session.latest.corners.length >= session.min_corners;
	return (
		<div className="flex flex-col gap-4">
			<CalibrationView session={session} />
			<p className="text-sm text-muted-foreground">
				Corners in view: {session.latest.corners.length} · Captured views: {session.frames.length} of at least{' '}
				{session.min_frames}. Shaded areas have no captured corners yet; cover the edges and corners.
			</p>
			<div className="flex flex-wrap gap-3">
				<Button
					disabled={!enough || busy}
					onClick={() => {
						capture.mutate(cameraParams(session.camera));
					}}
				>
					Capture view
				</Button>
				<Button
					variant="outline"
					disabled={session.frames.length < session.min_frames || busy}
					onClick={() => {
						solve.mutate(cameraParams(session.camera));
					}}
				>
					{solve.isPending ? 'Solving…' : 'Solve'}
				</Button>
				<Button
					variant="ghost"
					onClick={() => {
						stop.mutate(cameraParams(session.camera));
					}}
				>
					End session
				</Button>
			</div>
			<ErrorText error={capture.error ?? solve.error} />
			{solution ? (
				<Panel title={solution.accepted ? 'Calibration ready' : 'Calibration error is too high'}>
					<DataList
						values={{
							'RMS error': `${fmt(solution.calibration.rms, 3)} px (limit ${session.max_rms} px)`,
							'fx, fy': `${fmt(solution.calibration.fx, 2)}, ${fmt(solution.calibration.fy, 2)}`,
							'cx, cy': `${fmt(solution.calibration.cx, 2)}, ${fmt(solution.calibration.cy, 2)}`,
							Distortion: solution.calibration.distortion.map((k) => k.toFixed(5)).join(', '),
							'Views used': solution.used.length,
							'Outlier views': solution.rejected.length > 0 ? solution.rejected.map((i) => i + 1).join(', ') : 'None',
						}}
					/>
					{solution.accepted ? (
						<Button
							className="self-start"
							disabled={overrides.isPending}
							onClick={() => {
								overrides.set([[['cameras', session.camera, 'calibrations', resolution], solution.calibration]], {
									onSettled: () => {
										stop.mutate(cameraParams(session.camera));
									},
								});
							}}
						>
							Apply to {session.camera} at {resolution}
						</Button>
					) : (
						<p className="text-sm text-muted-foreground">
							Capture sharper views at more distances and angles, then solve again.
						</p>
					)}
					<ErrorText error={overrides.error} />
				</Panel>
			) : null}
		</div>
	);
}

export default function Calibration() {
	const status = useStatus();
	const settings = useSettings();
	const cameras = status.data?.cameras ?? [];
	const [camera, setCamera] = useState('');
	const selected = camera || cameras[0]?.name || '';
	const session = $api.useQuery('get', '/api/calibration/{camera}', cameraParams(selected), {
		enabled: Boolean(selected),
		refetchInterval: 500,
	});
	const start = $api.useMutation('post', '/api/calibration/{camera}', { onSuccess: setSession });
	return (
		<>
			<PageTitle>Calibration</PageTitle>
			<div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
				<Panel
					title="Camera"
					action={
						<NativeSelect
							value={selected}
							onChange={(e) => {
								setCamera(e.target.value);
							}}
						>
							{cameras.map((c) => (
								<NativeSelectOption key={c.name} value={c.name}>
									{c.name} · {c.mode}
								</NativeSelectOption>
							))}
						</NativeSelect>
					}
				>
					{selected ? (
						session.data && !session.isError ? (
							// No session is a normal state (the service answers 409), not an error.
							<SessionPanel session={session.data} />
						) : (
							<>
								<p className="text-sm text-muted-foreground">
									Calibrate at the mode the camera will run in. Hold the board flat and sharp, and capture views at
									varied distances and tilts.
								</p>
								<Button
									className="self-start"
									disabled={start.isPending}
									onClick={() => {
										start.mutate(cameraParams(selected));
									}}
								>
									Start calibrating {selected}
								</Button>
								<ErrorText error={start.error} />
							</>
						)
					) : (
						<p className="text-sm text-muted-foreground">Name a camera before calibrating it.</p>
					)}
				</Panel>
				<Panel title="Board">{settings.data ? <BoardForm settings={settings.data} /> : null}</Panel>
			</div>
		</>
	);
}
