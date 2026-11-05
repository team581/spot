import { useState, useReducer } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../../api';
import { errorMessage, useDashboard } from '../../dashboard';
import { Feedback, Panel, fmt, date, saveJson } from '../../components/common';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { readStatus, useOperation, useStatus } from '../../queries';
import type { Status } from '../../types';
export default function Results() {
	const { selections, announce } = useDashboard(),
		status = useStatus(),
		apply = useOperation<'calibration/apply'>(),
		restore = useOperation<'configuration/restore'>(),
		importing = useOperation<'configuration/import'>(),
		exporting = useMutation({
			mutationFn: async () => saveJson(await api('/api/configuration'), 'spot-calibrations.json'),
		}),
		[notice, setNotice] = useState(''),
		selected = selections.results;
	const [, redraw] = useReducer((n) => n + 1, 0);
	const sessions = status.calibration.cameras,
		passing = (id: string) => sessions[id]?.fit?.accepted && sessions[id]?.holdout?.accepted;
	return (
		<>
			<Panel title="Results">
				<Table>
					<TableHeader>
						<TableRow>
							<TableHead>Camera</TableHead>
							<TableHead>Fit RMS</TableHead>
							<TableHead>Validation RMS</TableHead>
							<TableHead>Fit / validation views</TableHead>
							<TableHead>Result</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{Object.entries(sessions).length ? (
							Object.entries(sessions).map(([id, s]) => (
								<TableRow key={id}>
									<TableCell>
										<Label>
											<Checkbox
												checked={selected.has(id)}
												onCheckedChange={(checked) => {
													checked ? selected.add(id) : selected.delete(id);
													redraw();
												}}
											/>
											{status.cameras.find((c) => c.identity === id)?.name || id.slice(0, 8)}
										</Label>
									</TableCell>
									<TableCell>{fmt(s.fit?.rms_reprojection_error_px, 2)} px</TableCell>
									<TableCell>{fmt(s.holdout?.rms_px, 2)} px</TableCell>
									<TableCell>
										{s.fit_views} / {s.holdout_views}
									</TableCell>
									<TableCell className={passing(id) ? 'text-success' : 'text-warning'}>
										{passing(id) ? '✓ Pass' : s.reason || s.fit?.reason || 'Capture required'}
									</TableCell>
								</TableRow>
							))
						) : (
							<TableRow>
								<TableCell colSpan={5}>Select cameras on Capture</TableCell>
							</TableRow>
						)}
					</TableBody>
				</Table>
				<div className="flex flex-wrap items-center gap-3">
					<Button
						variant="outline"
						onClick={() => {
							selected.clear();
							for (const id of Object.keys(sessions)) if (passing(id)) selected.add(id);
							redraw();
						}}
					>
						Select passing
					</Button>
					<Button
						disabled={Boolean(
							apply.isPending || !selected.size || [...selected].some((id) => !passing(id) || sessions[id]?.solving),
						)}
						onClick={() =>
							apply.mutate({
								operation: 'calibration/apply',
								payload: { identities: [...selected], revision: readStatus().revision },
							})
						}
					>
						Apply selected
					</Button>
					<small id="apply-status" className="text-muted-foreground">
						{apply.isPending
							? 'Applying calibration…'
							: apply.isSuccess
								? 'Applied · ' + apply.data.applied_generation
								: apply.error?.message}
					</small>
				</div>
			</Panel>
			<Panel title="History" className="history-panel">
				{(status.history ?? []).filter((h) => h.cameras?.length || h.error).length ? (
					(status.history ?? [])
						.filter((h) => h.cameras?.length || h.error)
						.map((h) => (
							<HistoryEntry
								key={h.generation}
								entry={h}
								onRestore={(ids) =>
									restore.mutate(
										{
											operation: 'configuration/restore',
											payload: { generation: h.generation, calibration_ids: ids, revision: readStatus().revision },
										},
										{ onSuccess: () => announce('Selected calibration group restored') },
									)
								}
							/>
						))
				) : (
					<p className="text-muted-foreground">No activated calibration history</p>
				)}
				<div className="flex flex-wrap items-center gap-2">
					<Button variant="outline" onClick={() => exporting.mutate()}>
						Export calibrations
					</Button>
					<Label className="gap-2">
						Import calibrations
						<Input
							className="w-auto"
							type="file"
							accept="application/json,.json"
							onChange={async (e) => {
								const file = e.target.files?.[0];
								if (!file) return;
								if (file.size > 2 * 1024 * 1024) {
									setNotice('Import exceeds 2 MiB');
									return;
								}
								let document;
								try {
									document = JSON.parse(await file.text());
								} catch (error) {
									setNotice(errorMessage(error));
									return;
								}
								setNotice('');
								importing.mutate(
									{ operation: 'configuration/import', payload: { document, revision: readStatus().revision } },
									{ onSuccess: () => announce('Calibrations imported') },
								);
							}}
						/>
					</Label>
				</div>
				<Feedback id="history-feedback">
					{notice || restore.error?.message || importing.error?.message || exporting.error?.message}
				</Feedback>
			</Panel>
		</>
	);
}
function HistoryEntry({
	entry: h,
	onRestore,
}: {
	entry: NonNullable<Status['history']>[number];
	onRestore: (ids: string[]) => void;
}) {
	const { selections } = useDashboard(),
		status = useStatus(),
		[, redraw] = useReducer((n) => n + 1, 0);
	const [selected] = useState(() => selections.history.get(h.generation) ?? new Set<string>());
	return (
		<div className="flex flex-col items-start gap-2">
			<span>
				<strong>{h.generation.slice(0, 12)}</strong> {h.active ? '· active' : ''}
			</span>
			<div className="flex flex-col gap-2">
				{h.cameras.map((record) => {
					const current = status.cameras.find((c) => c.identity === record.identity),
						compatible = current?.connected && current.mode_signature === record.mode_signature;
					return (
						<Label key={record.id}>
							<Checkbox
								checked={selected.has(record.id)}
								disabled={Boolean(!compatible || h.active)}
								onCheckedChange={(checked) => {
									checked ? selected.add(record.id) : selected.delete(record.id);
									selections.history.set(h.generation, selected);
									redraw();
								}}
							/>
							{current?.name || record.identity.slice(0, 8)} · {date(record.saved_at)}{' '}
							{compatible ? '' : '· current mode unavailable or incompatible'}
						</Label>
					);
				})}
			</div>
			{h.error ? (
				<span className="text-warning">{h.error}</span>
			) : (
				<Button
					variant="outline"
					disabled={Boolean(h.active || !selected.size)}
					onClick={() => onRestore([...selected])}
				>
					Restore selected
				</Button>
			)}
		</div>
	);
}
