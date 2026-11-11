import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { client, unwrap, type Settings } from '../api';
import { queryClient, useEditOverrides, useSettings, useStatus } from '../queries';
import { useCharuco, useImage } from '../live';
import { DataList, ErrorText, fmt, PageTitle, Panel } from '../components/common';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type { components } from '../api.gen';

type Board = components['schemas']['Board'];
type Session = components['schemas']['CalibrationView'];
const dictionaries: Board['dictionary'][] = ['4x4_50', '4x4_100', '5x5_50', '5x5_100', '6x6_50', '6x6_250'];
/** Coverage hint grid: cells with a captured corner count as covered. */
const GRID = 6;

function BoardForm({ settings }: { settings: Settings }) {
	const board = settings.calibration_board;
	const [draft, setDraft] = useState({
		squares_x: String(board.squares_x),
		squares_y: String(board.squares_y),
		square_mm: String(board.square_size * 1000),
		marker_mm: String(board.marker_size * 1000),
		dictionary: board.dictionary,
	});
	const save = useMutation({
		mutationFn: (body: Settings) => unwrap(client.PUT('/api/settings', { body })),
		onSuccess: (data) => queryClient.setQueryData(['settings'], data),
	});
	const field = (key: 'squares_x' | 'squares_y' | 'square_mm' | 'marker_mm', label: string) => (
		<div className="flex flex-col gap-2">
			<Label htmlFor={key}>{label}</Label>
			<Input
				id={key}
				inputMode="decimal"
				value={draft[key]}
				onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
			/>
		</div>
	);
	return (
		<form
			className="flex flex-col gap-4"
			onSubmit={(e) => {
				e.preventDefault();
				save.mutate({
					...settings,
					calibration_board: {
						squares_x: Number(draft.squares_x),
						squares_y: Number(draft.squares_y),
						square_size: Number(draft.square_mm) / 1000,
						marker_size: Number(draft.marker_mm) / 1000,
						dictionary: draft.dictionary,
					},
				});
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
					onChange={(e) => setDraft({ ...draft, dictionary: e.target.value as Board['dictionary'] })}
				>
					{dictionaries.map((d) => (
						<NativeSelectOption key={d} value={d}>
							{d.toUpperCase()}
						</NativeSelectOption>
					))}
				</NativeSelect>
			</div>
			<div className="flex flex-wrap items-center gap-3">
				<Button type="submit" disabled={save.isPending}>
					Save board
				</Button>
				<Button variant="outline" render={<a href="/api/calibration/board.svg" target="_blank" rel="noreferrer" />}>
					Open printable board
				</Button>
			</div>
			<p className="text-sm text-muted-foreground">
				Print at 100% scale and measure a square. Save the measured size before calibrating.
			</p>
			<ErrorText error={save.error} />
		</form>
	);
}

/** Live image with the detected board corners, captured corners, and coverage of the image. */
function CalibrationView({ session }: { session: Session }) {
	const image = useImage(session.camera),
		charuco = useCharuco(session.camera);
	const width = session.width ?? charuco?.width ?? 1280,
		height = session.height ?? charuco?.height ?? 800;
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
	const action = useMutation({
		mutationFn: (step: 'capture' | 'solve') =>
			unwrap(client.POST(`/api/calibration/{camera}/${step}`, { params: { path: { camera: session.camera } } })),
		onSuccess: (data) => queryClient.setQueryData(['calibration', session.camera], data),
	});
	const stop = useMutation({
		mutationFn: () => client.DELETE('/api/calibration/{camera}', { params: { path: { camera: session.camera } } }),
		onSuccess: () => queryClient.removeQueries({ queryKey: ['calibration', session.camera] }),
	});
	const solution = session.solution;
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
				<Button disabled={!enough || action.isPending} onClick={() => action.mutate('capture')}>
					Capture view
				</Button>
				<Button
					variant="outline"
					disabled={session.frames.length < session.min_frames || action.isPending}
					onClick={() => action.mutate('solve')}
				>
					{action.isPending && action.variables === 'solve' ? 'Solving…' : 'Solve'}
				</Button>
				<Button variant="ghost" onClick={() => stop.mutate()}>
					End session
				</Button>
			</div>
			<ErrorText error={action.error} />
			{solution ? (
				<Panel title={solution.accepted ? 'Calibration ready' : 'Calibration error is too high'}>
					<DataList
						values={{
							'RMS error': `${fmt(solution.calibration.rms, 3)} px (limit ${session.max_rms} px)`,
							'fx, fy': `${fmt(solution.calibration.fx, 2)}, ${fmt(solution.calibration.fy, 2)}`,
							'cx, cy': `${fmt(solution.calibration.cx, 2)}, ${fmt(solution.calibration.cy, 2)}`,
							Distortion: solution.calibration.distortion.map((k) => k.toFixed(5)).join(', '),
							'Views used': solution.used.length,
							'Outlier views': solution.rejected.length ? solution.rejected.map((i) => i + 1).join(', ') : 'None',
						}}
					/>
					{solution.accepted ? (
						<Button
							className="self-start"
							disabled={overrides.isPending}
							onClick={() =>
								overrides.set([[['cameras', session.camera, 'calibrations', resolution], solution.calibration]], {
									onSettled: () => stop.mutate(),
								})
							}
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
	const status = useStatus(),
		settings = useSettings(),
		cameras = status.data?.cameras ?? [];
	const [camera, setCamera] = useState('');
	const selected = camera || cameras[0]?.name || '';
	const session = useQuery({
		queryKey: ['calibration', selected],
		// No session is a normal state, not an error.
		queryFn: async () =>
			(await client.GET('/api/calibration/{camera}', { params: { path: { camera: selected } } })).data ?? null,
		enabled: Boolean(selected),
		refetchInterval: 500,
	});
	const start = useMutation({
		mutationFn: () => unwrap(client.POST('/api/calibration/{camera}', { params: { path: { camera: selected } } })),
		onSuccess: (data) => queryClient.setQueryData(['calibration', selected], data),
	});
	return (
		<>
			<PageTitle>Calibration</PageTitle>
			<div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
				<Panel
					title="Camera"
					action={
						<NativeSelect value={selected} onChange={(e) => setCamera(e.target.value)}>
							{cameras.map((c) => (
								<NativeSelectOption key={c.name} value={c.name}>
									{c.name} · {c.mode}
								</NativeSelectOption>
							))}
						</NativeSelect>
					}
				>
					{!selected ? (
						<p className="text-sm text-muted-foreground">Name a camera before calibrating it.</p>
					) : session.data ? (
						<SessionPanel session={session.data} />
					) : (
						<>
							<p className="text-sm text-muted-foreground">
								Calibrate at the mode the camera will run in. Hold the board flat and sharp, and capture views at varied
								distances and tilts.
							</p>
							<Button className="self-start" disabled={start.isPending} onClick={() => start.mutate()}>
								Start calibrating {selected}
							</Button>
							<ErrorText error={start.error} />
						</>
					)}
				</Panel>
				<Panel title="Board">{settings.data ? <BoardForm settings={settings.data} /> : null}</Panel>
			</div>
		</>
	);
}
