import { useState, useReducer } from 'react';
import { useDashboard, errorMessage } from '../../dashboard';
import { Feed } from '../../components/Feed';
import type { Action } from '../Calibration';
const boardLabels: Record<string, string> = {
	dictionary: 'Dictionary',
	squares_x: 'Squares X',
	squares_y: 'Squares Y',
	square_length_m: 'Square length (m)',
	marker_length_m: 'Marker length (m)',
};
export default function Capture({ action, onError }: { action: Action; onError: (message: string) => void }) {
	const { status, read, mutate, selections } = useDashboard(),
		selected = selections.capture;
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
		if (!camera.logical_name && (!camera.standalone_setup || status.lock_reason))
			try {
				await mutate('device/setup', { identity: choice, revision: read().revision });
			} catch (error) {
				onError(errorMessage(error));
				return;
			}
		selected.add(choice);
		if (!(await action('select', { identities: [...selected] }))) selected.delete(choice);
		setCards([...selected]);
	}
	return (
		<div className="calibration-layout">
			<div>
				<div className="inline-actions">
					<select aria-label="Camera to add" value={choice} onChange={(e) => setChoice(e.target.value)}>
						<option value="">Select camera</option>
						{usable.map((c) => (
							<option value={c.identity} key={c.identity}>
								{c.name}
							</option>
						))}
					</select>
					<button onClick={() => void add()}>Add camera</button>
				</div>
				<div className="calibration-grid spaced">
					{cards.length ? (
						cards.map((id) => (
							<CalibrationCard
								key={id}
								id={id}
								selected={selected.has(id)}
								onSelect={async (checked) => {
									checked ? selected.add(id) : selected.delete(id);
									redraw();
									await action('select', { identities: [...selected] });
								}}
								action={action}
							/>
						))
					) : (
						<p className="muted">Add a connected camera to begin.</p>
					)}
				</div>
			</div>
			<section className="panel board">
				<h2>Board</h2>
				<div className="board-fields">
					{Object.entries(boardLabels).map(([key, label]) => (
						<label key={key}>
							{label}
							<input
								type="text"
								inputMode={key === 'dictionary' ? 'text' : 'decimal'}
								value={board[key] ?? ''}
								onChange={(e) => setBoard({ ...board, [key]: e.target.value })}
							/>
						</label>
					))}
					<label>
						Lens model
						<select value={model} onChange={(e) => setModel(e.target.value)}>
							<option value="plumb_bob">Plumb bob</option>
							<option value="rational">Rational</option>
						</select>
					</label>
					<label>
						Minimum fit views
						<input type="text" inputMode="numeric" value={minViews} onChange={(e) => setMinViews(e.target.value)} />
					</label>
				</div>
				<button
					className="spaced"
					disabled={Boolean(status.lock_reason)}
					onClick={async () => {
						const values = Object.fromEntries(
							Object.keys(status.calibration.board ?? {}).map((key) => [
								key,
								key === 'dictionary' ? board[key] : Number(board[key]),
							]),
						);
						const result = await action('board', {
							board: values,
							options: { ...status.calibration.options, model, min_frames: Number(minViews) },
						});
						if (result && selected.size) {
							await action('select', { identities: [...selected] });
							setCards([...selected]);
						}
					}}
				>
					Update board
				</button>
				<label className="spaced">
					Group capture set
					<select value={phase} onChange={(e) => setPhase(e.target.value)}>
						<option value="fit">Fitting captures</option>
						<option value="holdout">Validation captures</option>
					</select>
				</label>
				<button
					className="primary spaced"
					disabled={Boolean(
						status.lock_reason || !selected.size || Object.values(status.calibration.cameras).some((s) => s.solving),
					)}
					onClick={() => void action('start-all', { phase })}
				>
					Start automatic capture
				</button>
				<p>
					<a href="/docs/operator/calibrate/">Capture and validation guide</a>
				</p>
			</section>
		</div>
	);
}
function CalibrationCard({
	id,
	selected,
	onSelect,
	action,
}: {
	id: string;
	selected: boolean;
	onSelect: (checked: boolean) => Promise<void>;
	action: Action;
}) {
	const { status } = useDashboard(),
		camera = status.cameras.find((c) => c.identity === id),
		session = status.calibration.cameras[id],
		[phase, setPhase] = useState('fit');
	return (
		<section className="panel calibration-card">
			<header>
				<input
					type="checkbox"
					checked={selected}
					aria-label={'Select ' + camera?.name}
					onChange={(e) => void onSelect(e.target.checked)}
				/>
				<strong>{camera?.name || id.slice(0, 8)}</strong>
			</header>
			<Feed id={id} calibration />
			<progress
				className="coverage-progress"
				max="1"
				value={Math.max(0, Math.min(1, session?.coverage?.coverage_progress || 0))}
				aria-label="Calibration coverage"
			/>
			<div className="capture-stats">
				{session
					? `${session.fit_views} fit / ${session.holdout_views} validation views · ${Math.round((session.coverage?.coverage_progress || 0) * 100)}% coverage · ${session.board_detected ? 'Board detected' : 'Board not detected'}`
					: 'Start a calibration session'}
			</div>
			<div className="actions">
				<select aria-label="Capture set" value={phase} onChange={(e) => setPhase(e.target.value)}>
					<option value="fit">Fitting captures</option>
					<option value="holdout">Validation captures</option>
				</select>
				{['start', 'capture', 'compute', 'validate'].map((operation) => (
					<button
						key={operation}
						disabled={Boolean(status.lock_reason || session?.solving)}
						onClick={() =>
							void action(operation === 'start' && session?.running ? 'pause' : operation, {
								identity: id,
								phase,
								automatic: true,
							})
						}
					>
						{operation === 'start'
							? session?.running
								? 'Pause'
								: 'Start'
							: operation === 'compute'
								? 'Calibrate'
								: operation === 'capture'
									? 'Capture'
									: 'Validate'}
					</button>
				))}
			</div>
			<p className="feedback">{session?.reason || ''}</p>
		</section>
	);
}
