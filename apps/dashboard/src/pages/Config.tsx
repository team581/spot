import { useRef, useState } from 'react';
import { diffOverrides, overridesFor, parseOverrides } from '../overrides';
import type { Json, Overrides } from '../overrides';
import { useConfig, useEditOverrides } from '../queries';
import { DataList, ErrorText, PageTitle, Panel } from '../components/common';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';

const show = (value: Json | undefined) =>
	value === undefined ? (
		<span className="text-muted-foreground">unset</span>
	) : value === null ? (
		<span className="text-muted-foreground">removed</span>
	) : (
		JSON.stringify(value)
	);

function robotConfig(toml: string | null | undefined) {
	try {
		return toml ? parseOverrides(toml) : undefined;
	} catch {
		// The rejection reason is shown with the config error.
		return undefined;
	}
}

function Merged({ toml }: { toml: string }) {
	const area = useRef<HTMLTextAreaElement>(null);
	const [copied, setCopied] = useState('');
	const copy = async () => {
		try {
			await navigator.clipboard.writeText(toml);
			setCopied('Copied');
		} catch {
			// The clipboard API needs a secure context, which Spot's plain HTTP address is not.
			area.current?.select();
			setCopied('Selected, press Ctrl+C to copy');
		}
	};
	return (
		<Panel
			title="Merged config"
			action={
				<div className="flex items-center gap-2">
					<span className="text-xs text-muted-foreground">{copied}</span>
					<Button variant="outline" size="sm" onClick={() => void copy()} disabled={!toml}>
						Copy
					</Button>
				</div>
			}
		>
			<p className="text-sm text-muted-foreground">The robot config with overrides applied. Copy it into robot code.</p>
			<Textarea
				ref={area}
				readOnly
				value={toml}
				onFocus={(e) => {
					e.target.select();
				}}
				className="min-h-80 font-mono text-xs"
			/>
		</Panel>
	);
}

function Paste({ robot, edit }: { robot: Json | undefined; edit: ReturnType<typeof useEditOverrides> }) {
	const [text, setText] = useState('');
	const [error, setError] = useState<Error | null>(null);
	const apply = () => {
		let target: Overrides;
		try {
			target = parseOverrides(text);
		} catch (error_) {
			setError(error_ instanceof Error ? error_ : new Error(String(error_)));
			return;
		}
		setError(null);
		edit.mutate(() => overridesFor(robot, target), {
			onError: setError,
			onSuccess: () => {
				setText('');
			},
		});
	};
	return (
		<Panel
			title="Paste config"
			action={
				<Button size="sm" disabled={!text.trim() || edit.isPending} onClick={apply}>
					Apply
				</Button>
			}
		>
			<p className="text-sm text-muted-foreground">
				Replace the config with TOML. It's saved as overrides, so discarding them returns to the robot config.
			</p>
			<Textarea
				value={text}
				onChange={(e) => {
					setText(e.target.value);
				}}
				placeholder="Paste a spot.toml"
				className="min-h-40 font-mono text-xs"
			/>
			<ErrorText error={error} />
		</Panel>
	);
}

export default function Config() {
	const { data: view, error } = useConfig();
	const edit = useEditOverrides();
	const robot = robotConfig(view?.robot_config);
	// oxlint-disable-next-line typescript/no-unsafe-type-assertion -- The backend returns JSON overrides validated against the robot config schema.
	const differences = diffOverrides(robot, (view?.overrides ?? {}) as Overrides);
	return (
		<>
			<PageTitle>Config</PageTitle>
			<ErrorText error={error} />
			{view?.error ? (
				<Alert variant="destructive">
					<AlertTitle>Config rejected</AlertTitle>
					<AlertDescription className="whitespace-pre-wrap">{view.error}</AlertDescription>
				</Alert>
			) : null}
			<Panel title="Source">
				<DataList
					values={{
						'Robot config': view?.robot_config_live
							? 'Live from the robot'
							: view?.robot_config
								? 'Cached from the last robot connection'
								: 'None received',
						'Field layout': view?.field_layout ? `${view.field_layout.tags.length} tags` : 'None',
					}}
				/>
			</Panel>
			<Panel
				title="Overrides"
				action={
					<Button
						variant="destructive"
						size="sm"
						disabled={differences.length === 0 || edit.isPending}
						onClick={() => {
							if (confirm('Discard all dashboard overrides?')) {
								edit.mutate(() => ({}));
							}
						}}
					>
						Discard overrides
					</Button>
				}
			>
				{differences.length > 0 ? (
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Key</TableHead>
								<TableHead>Robot config</TableHead>
								<TableHead>Override</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{differences.map((d) => (
								<TableRow key={d.path}>
									<TableCell className="font-mono text-xs">{d.path}</TableCell>
									<TableCell className="font-mono text-xs">{show(d.before)}</TableCell>
									<TableCell className="font-mono text-xs">{show(d.after)}</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				) : (
					<p className="text-sm text-muted-foreground">No overrides. Spot is using the robot config as is.</p>
				)}
				<ErrorText error={edit.error} />
			</Panel>
			{view ? <Merged toml={view.merged} /> : null}
			<Paste robot={robot} edit={edit} />
		</>
	);
}
