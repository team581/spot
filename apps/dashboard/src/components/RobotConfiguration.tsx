import { useState } from 'react';
import { api, submit } from '../api';
import { Feedback, Panel, saveJson } from './common';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { errorMessage, useDashboard } from '../dashboard';
import { readStatus, useStatus, useTask } from '../queries';

export default function RobotConfiguration() {
	const { announce } = useDashboard(),
		status = useStatus(),
		task = useTask(),
		busy = task.isPending;
	const [text, setText] = useState('');
	const [revision, setRevision] = useState('');
	const [notice, setNotice] = useState('');
	const run = (work: () => Promise<void>) => {
		setNotice('');
		task.mutate(work);
	};

	const load = (defaults = false) =>
		run(async () => {
			// Keep the revision observed before the request; a concurrent edit must conflict.
			const expected = readStatus().revision;
			setText(JSON.stringify(await api(defaults ? '/api/robot/defaults' : '/api/robot/configuration'), null, 2));
			setRevision(expected);
		});
	const apply = () =>
		run(async () => {
			const document = JSON.parse(text) as Record<string, unknown>;
			setRevision((await submit('configuration/apply', { document, revision })).revision);
			announce('Dashboard overrides saved.');
		});
	const clear = (path = '') =>
		run(async () => {
			const applied = await submit('configuration/clear-overrides', { path, revision: readStatus().revision });
			setRevision(applied.revision);
			if (text) setText(JSON.stringify(await api('/api/robot/configuration'), null, 2));
			announce(path ? 'Override cleared' : 'All overrides cleared');
		});
	const download = () => {
		try {
			saveJson(JSON.parse(text), 'spot-config.json');
		} catch (e) {
			setNotice(errorMessage(e));
		}
	};
	return (
		<Panel title="Robot configuration" className="lg:col-span-2">
			<p>
				Robot code supplies the baseline. Dashboard overrides are saved on Spot and take priority until you clear them,
				including after restarts and deployments.
			</p>
			{status.has_overrides ? <p className="text-warning">Saved dashboard overrides are active.</p> : null}
			{(status.override_paths ?? []).length > 0 ? (
				<>
					<ul className="flex flex-col gap-1">
						{status.override_paths?.map((path) => (
							<li key={path} className="flex items-center gap-2">
								<code>{path}</code>{' '}
								<Button variant="outline" disabled={busy || Boolean(status.lock_reason)} onClick={() => clear(path)}>
									Clear override
								</Button>
							</li>
						))}
					</ul>
					<Button variant="outline" disabled={busy || Boolean(status.lock_reason)} onClick={() => clear()}>
						Clear all overrides
					</Button>
				</>
			) : null}
			<p>
				Download the effective configuration and replace <code>src/main/deploy/spot-config.json</code> in the robot
				project. Calibration results can be copied between this file and standalone calibration exports.
			</p>
			<div className="flex flex-wrap items-center gap-2">
				<Button variant="outline" disabled={busy || !status.fresh} onClick={() => load()}>
					Read current configuration
				</Button>
				<Button variant="outline" disabled={busy || !status.fresh} onClick={() => load(true)}>
					Read deployed defaults
				</Button>
				<Label className="gap-2">
					Open configuration file
					<Input
						className="w-auto"
						type="file"
						accept="application/json,.json"
						disabled={busy || !status.fresh}
						onChange={async (e) => {
							const file = e.target.files?.[0];
							if (!file) return;
							if (file.size > 256 * 1024) {
								setNotice('Configuration exceeds 256 KiB');
								return;
							}
							try {
								const expected = status.revision;
								setText(JSON.stringify(JSON.parse(await file.text()), null, 2));
								setRevision(expected);
								setNotice('');
							} catch (error) {
								setNotice(errorMessage(error));
							}
						}}
					/>
				</Label>
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
					<div className="flex flex-wrap items-center gap-2">
						<Button disabled={busy || Boolean(status.lock_reason) || !status.fresh} onClick={() => apply()}>
							Save dashboard overrides
						</Button>
						<Button variant="outline" disabled={busy} onClick={download}>
							Download spot-config.json
						</Button>
						<Button
							variant="outline"
							disabled={busy}
							onClick={() =>
								void navigator.clipboard.writeText(text).then(
									() => announce('Configuration copied'),
									(e: unknown) => setNotice(errorMessage(e)),
								)
							}
						>
							Copy configuration
						</Button>
					</div>
				</>
			) : null}
			<Feedback>{busy ? 'Applying settings…' : notice || task.error?.message}</Feedback>
		</Panel>
	);
}
