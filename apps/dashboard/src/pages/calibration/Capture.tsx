import { Link } from '@tanstack/react-router';
import { useState, useReducer } from 'react';
import { useDashboard } from '../../dashboard';
import { Feed } from '../../components/Feed';
import { readStatus, useStatus } from '../../queries';
import type { CalibrationOperation } from '../Calibration';
import { Feedback, Panel } from '../../components/common';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Progress } from '@/components/ui/progress';
const boardLabels: Record<string, string> = {
	dictionary: 'Dictionary',
	squares_x: 'Squares X',
	squares_y: 'Squares Y',
	square_length_m: 'Square length (m)',
	marker_length_m: 'Marker length (m)',
};
export default function Capture({ operation }: { operation: CalibrationOperation }) {
	const { selections } = useDashboard(),
		status = useStatus(),
		selected = selections.capture;
	const select = () =>
		operation.mutateAsync({
			operation: 'calibration/select',
			payload: { identities: [...selected], revision: readStatus().revision },
		});
	const [cards, setCards] = useState(() => {
		for (const id of Object.keys(status.calibration.cameras)) selected.add(id);
		return [...selected].filter((id) =>
			status.cameras.some((c) => c.identity === id && (c.logical_name || c.connected)),
		);
	});
	const [, redraw] = useReducer((n) => n + 1, 0),
		[choice, setChoice] = useState(''),
		[phase, setPhase] = useState('fit');
	const [board, setBoard] = useState(status.calibration.board ?? {}),
		[model, setModel] = useState(String(status.calibration.options?.model || 'plumb_bob')),
		[minViews, setMinViews] = useState(String(status.calibration.options?.min_frames || 15));
	const usable = status.cameras.filter((c) => c.logical_name || c.connected);
	async function add() {
		if (!choice) return;
		const camera = status.cameras.find((c) => c.identity === choice);
		if (!camera) return;
		try {
			if (!camera.logical_name && (!camera.standalone_setup || status.lock_reason))
				await operation.mutateAsync({
					operation: 'device/setup',
					payload: { identity: choice, revision: readStatus().revision },
				});
			selected.add(choice);
			await select();
		} catch {
			// The page shows the operation error.
			selected.delete(choice);
		}
		setCards([...selected]);
	}
	return (
		<div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
			<div className="flex flex-col gap-4">
				<div className="flex flex-wrap gap-2">
					<NativeSelect aria-label="Camera to add" value={choice} onChange={(e) => setChoice(e.target.value)}>
						<NativeSelectOption value="">Select camera</NativeSelectOption>
						{usable.map((c) => (
							<NativeSelectOption value={c.identity} key={c.identity}>
								{c.name}
							</NativeSelectOption>
						))}
					</NativeSelect>
					<Button variant="outline" onClick={() => void add()}>
						Add camera
					</Button>
				</div>
				<div className="grid gap-4 sm:grid-cols-2">
					{cards.length ? (
						cards.map((id) => (
							<CalibrationCard
								key={id}
								id={id}
								selected={selected.has(id)}
								onSelect={async (checked) => {
									checked ? selected.add(id) : selected.delete(id);
									redraw();
									await select().catch(() => {});
								}}
								operation={operation}
							/>
						))
					) : (
						<p className="text-muted-foreground">Add a connected camera to begin.</p>
					)}
				</div>
			</div>
			<Panel title="Board" className="max-lg:order-first">
				<div className="grid gap-3 max-lg:grid-cols-2">
					{Object.entries(boardLabels).map(([key, label]) => (
						<Label key={key} className="flex-col items-stretch">
							{label}
							<Input
								type="text"
								inputMode={key === 'dictionary' ? 'text' : 'decimal'}
								value={board[key] ?? ''}
								onChange={(e) => setBoard({ ...board, [key]: e.target.value })}
							/>
						</Label>
					))}
					<Label className="flex-col items-stretch">
						Lens model
						<NativeSelect className="w-full" value={model} onChange={(e) => setModel(e.target.value)}>
							<NativeSelectOption value="plumb_bob">Plumb bob</NativeSelectOption>
							<NativeSelectOption value="rational">Rational</NativeSelectOption>
						</NativeSelect>
					</Label>
					<Label className="flex-col items-stretch">
						Minimum fit views
						<Input type="text" inputMode="numeric" value={minViews} onChange={(e) => setMinViews(e.target.value)} />
					</Label>
				</div>
				<Button
					variant="outline"
					disabled={Boolean(status.lock_reason)}
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
								payload: {
									board: values,
									options: { ...status.calibration.options, model, min_frames: Number(minViews) },
									revision: readStatus().revision,
								},
							});
							if (selected.size) {
								await select();
								setCards([...selected]);
							}
						} catch {
							// The page shows the operation error.
						}
					}}
				>
					Update board
				</Button>
				<Label className="flex-col items-stretch">
					Group capture set
					<NativeSelect className="w-full" value={phase} onChange={(e) => setPhase(e.target.value)}>
						<NativeSelectOption value="fit">Fitting captures</NativeSelectOption>
						<NativeSelectOption value="holdout">Validation captures</NativeSelectOption>
					</NativeSelect>
				</Label>
				<Button
					disabled={Boolean(
						status.lock_reason || !selected.size || Object.values(status.calibration.cameras).some((s) => s.solving),
					)}
					onClick={() =>
						operation.mutate({
							operation: 'calibration/start-all',
							payload: { phase, revision: readStatus().revision },
						})
					}
				>
					Start automatic capture
				</Button>
				<p>
					<Link to="/help/$" params={{ _splat: 'operator/cameras/' }} hash="calibrate">
						Capture and validation guide
					</Link>
				</p>
			</Panel>
		</div>
	);
}
function CalibrationCard({
	id,
	selected,
	onSelect,
	operation,
}: {
	id: string;
	selected: boolean;
	onSelect: (checked: boolean) => Promise<void>;
	operation: CalibrationOperation;
}) {
	const status = useStatus(),
		camera = status.cameras.find((c) => c.identity === id),
		session = status.calibration.cameras[id],
		[phase, setPhase] = useState('fit');
	return (
		<Card size="sm" className="calibration-card px-3">
			<Label>
				<Checkbox
					checked={selected}
					aria-label={'Select ' + camera?.name}
					onCheckedChange={(checked) => void onSelect(checked)}
				/>
				<strong>{camera?.name || id.slice(0, 8)}</strong>
			</Label>
			<Feed id={id} calibration className="aspect-[2.4]" />
			<Progress
				value={Math.max(0, Math.min(100, (session?.coverage?.coverage_progress || 0) * 100))}
				aria-label="Calibration coverage"
			/>
			<div>
				{session
					? `${session.fit_views} fit / ${session.holdout_views} validation views · ${Math.round((session.coverage?.coverage_progress || 0) * 100)}% coverage · ${session.board_detected ? 'Board detected' : 'Board not detected'}`
					: 'Start a calibration session'}
			</div>
			<div className="flex flex-wrap gap-1.5">
				<NativeSelect aria-label="Capture set" value={phase} onChange={(e) => setPhase(e.target.value)}>
					<NativeSelectOption value="fit">Fitting captures</NativeSelectOption>
					<NativeSelectOption value="holdout">Validation captures</NativeSelectOption>
				</NativeSelect>
				{(['start', 'capture', 'compute', 'validate'] as const).map((action) => (
					<Button
						key={action}
						variant="outline"
						disabled={Boolean(status.lock_reason || session?.solving)}
						onClick={() =>
							operation.mutate({
								operation: `calibration/${action === 'start' && session?.running ? 'pause' : action}`,
								payload: { identity: id, phase, automatic: true, revision: readStatus().revision },
							})
						}
					>
						{action === 'start'
							? session?.running
								? 'Pause'
								: 'Start'
							: action === 'compute'
								? 'Calibrate'
								: action === 'capture'
									? 'Capture'
									: 'Validate'}
					</Button>
				))}
			</div>
			<Feedback>{session?.reason || ''}</Feedback>
		</Card>
	);
}
