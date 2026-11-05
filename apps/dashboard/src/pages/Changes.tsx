import { useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import { api, submit } from '../api';
import { errorMessage, useDashboard } from '../dashboard';
import { readStatus, useStatus, useTask } from '../queries';
import { count, describe, display } from '../state/changes';
import { Feedback, PageTitle, Panel, saveJson } from '../components/common';
import { Steps, type Step } from '../components/Steps';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';

const FILE = 'spot-config.json';

/** Where Spot's configuration is in the robot code → Spot → robot code loop. */
function lifecycle(loaded: boolean, connected: boolean, changes: number, flagged: number): Step[] {
	if (!loaded)
		return [
			{ label: 'Robot code', detail: 'Waiting for robot code to connect', state: 'current' },
			{ label: 'Edit on Spot', detail: 'Tune, calibrate, measure mounts', state: 'upcoming' },
			{ label: 'Copy to robot code', state: 'upcoming' },
			{ label: 'Deploy', state: 'upcoming' },
		];
	return [
		{ label: 'Robot code', detail: connected ? 'Connected' : 'Saved copy · robot disconnected', state: 'complete' },
		{
			label: 'Edit on Spot',
			detail: !changes
				? 'No changes'
				: count(changes, 'change', 'changes') + (flagged ? ` · ${flagged} changed in robot code since` : ''),
			state: flagged ? 'warning' : 'complete',
		},
		{
			label: 'Copy to robot code',
			detail: changes ? `Update ${FILE}` : 'Nothing to copy',
			state: changes ? 'current' : 'complete',
		},
		{
			label: 'Deploy',
			detail: changes ? 'Changes clear when code matches' : 'In sync',
			state: changes ? 'upcoming' : 'complete',
		},
	];
}

export default function Changes() {
	const { announce } = useDashboard(),
		status = useStatus(),
		task = useTask(),
		busy = task.isPending,
		overrides = status.overrides ?? [],
		loaded = Boolean(status.has_configuration);
	const [text, setText] = useState(''),
		[revision, setRevision] = useState('');
	const effective = () => api<unknown>('/api/robot/configuration');
	const revert = (path = '') =>
		task.mutate(async () => {
			await submit('configuration/clear-overrides', { path, revision: readStatus().revision });
			announce(path ? 'Reverted to robot code' : 'All changes reverted to robot code');
		});
	const edit = (defaults: boolean) =>
		task.mutate(async () => {
			// Keep the revision observed before the request; a concurrent edit must conflict.
			const expected = readStatus().revision;
			setText(JSON.stringify(await api(defaults ? '/api/robot/defaults' : '/api/robot/configuration'), null, 2));
			setRevision(expected);
		});
	return (
		<>
			<PageTitle>Changes</PageTitle>
			<Panel
				title={
					!loaded
						? 'No robot configuration'
						: overrides.length
							? `${count(overrides.length, 'setting differs', 'settings differ')} from robot code`
							: 'In sync'
				}
			>
				<Steps
					steps={lifecycle(
						loaded,
						Boolean(status.connected),
						overrides.length,
						overrides.filter((o) => o.code_changed).length,
					)}
				/>
				{overrides.length ? (
					<p className="text-muted-foreground">
						Edits on Spot take priority over robot code, including after restarts and deployments.
					</p>
				) : null}
				<div className="flex flex-wrap gap-2">
					<Button
						disabled={busy || !loaded}
						onClick={() =>
							task.mutate(async () => {
								await navigator.clipboard.writeText(JSON.stringify(await effective(), null, 2) + '\n');
								announce(`${FILE} copied`);
							})
						}
					>
						Copy {FILE}
					</Button>
					<Button
						variant="outline"
						disabled={busy || !loaded}
						onClick={() => task.mutate(async () => saveJson(await effective(), FILE))}
					>
						Download {FILE}
					</Button>
					{overrides.length ? (
						<Button variant="outline" disabled={busy} onClick={() => revert()}>
							Revert all
						</Button>
					) : null}
				</div>
				{overrides.length ? (
					<Table id="changes">
						<TableHeader>
							<TableRow>
								<TableHead>Setting</TableHead>
								<TableHead>Robot code</TableHead>
								<TableHead>Spot</TableHead>
								<TableHead />
							</TableRow>
						</TableHeader>
						<TableBody>
							{overrides.map((o) => {
								const { camera, setting } = describe(o.path, status.cameras);
								return (
									<TableRow key={o.path} data-path={o.path}>
										<TableCell title={o.path}>
											{camera ? <span className="text-muted-foreground">{camera} · </span> : null}
											{setting}
										</TableCell>
										<TableCell>
											{display(o.path, o.code_value)}
											{o.code_changed ? (
												<span className="flex items-center gap-1 text-xs text-warning">
													<TriangleAlert className="size-3" aria-hidden /> Changed in robot code since this edit
												</span>
											) : null}
										</TableCell>
										<TableCell className="font-semibold">{display(o.path, o.value)}</TableCell>
										<TableCell className="text-right">
											<Button variant="outline" size="sm" disabled={busy} onClick={() => revert(o.path)}>
												Revert
											</Button>
										</TableCell>
									</TableRow>
								);
							})}
						</TableBody>
					</Table>
				) : null}
				<Feedback id="page-feedback">{busy ? 'Applying…' : task.error?.message}</Feedback>
			</Panel>
			<Collapsible>
				<CollapsibleTrigger className="text-muted-foreground hover:text-foreground">Edit as JSON</CollapsibleTrigger>
				<CollapsibleContent className="mt-3">
					<Panel>
						<p>Saving creates Spot changes for every value that differs from robot code.</p>
						<div className="flex flex-wrap gap-2">
							<Button variant="outline" disabled={busy || !loaded} onClick={() => edit(false)}>
								Load current
							</Button>
							<Button variant="outline" disabled={busy || !loaded} onClick={() => edit(true)}>
								Load robot code
							</Button>
						</div>
						{text ? (
							<>
								<Label htmlFor="robot-configuration">Camera and processing configuration</Label>
								<Textarea
									className="font-mono"
									id="robot-configuration"
									rows={20}
									value={text}
									disabled={busy}
									spellCheck={false}
									onChange={(e) => setText(e.target.value)}
								/>
								<Button
									className="self-start"
									disabled={busy}
									onClick={() =>
										task.mutate(async () => {
											let document;
											try {
												document = JSON.parse(text) as Record<string, unknown>;
											} catch (e) {
												throw new Error(errorMessage(e));
											}
											setRevision((await submit('configuration/apply', { document, revision })).revision);
											announce('Changes saved on Spot');
										})
									}
								>
									Save on Spot
								</Button>
							</>
						) : null}
					</Panel>
				</CollapsibleContent>
			</Collapsible>
		</>
	);
}
