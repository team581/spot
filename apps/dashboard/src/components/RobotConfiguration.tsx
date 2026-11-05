import { useState } from 'react';
import { api, submit } from '../api';
import { saveJson } from './common';
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
		<section className="panel wide">
			<h2>Robot configuration</h2>
			<p>
				Robot code supplies the baseline. Dashboard overrides are saved on Spot and take priority until you clear them,
				including after restarts and deployments.
			</p>
			{status.has_overrides ? <p className="warning">Saved dashboard overrides are active.</p> : null}
			{(status.override_paths ?? []).length > 0 ? (
				<>
					<ul>
						{status.override_paths?.map((path) => (
							<li key={path}>
								<code>{path}</code>{' '}
								<button disabled={busy || Boolean(status.lock_reason)} onClick={() => clear(path)}>
									Clear override
								</button>
							</li>
						))}
					</ul>
					<button disabled={busy || Boolean(status.lock_reason)} onClick={() => clear()}>
						Clear all overrides
					</button>
				</>
			) : null}
			<p>
				Download the effective configuration and replace <code>src/main/deploy/spot-config.json</code> in the robot
				project. Calibration results can be copied between this file and standalone calibration exports.
			</p>
			<div className="inline-actions spaced">
				<button disabled={busy || !status.fresh} onClick={() => load()}>
					Read current configuration
				</button>
				<button disabled={busy || !status.fresh} onClick={() => load(true)}>
					Read deployed defaults
				</button>
				<label>
					Open configuration file{' '}
					<input
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
				</label>
			</div>
			{text ? (
				<>
					<label htmlFor="robot-configuration">Camera and processing configuration</label>
					<textarea
						id="robot-configuration"
						rows={20}
						value={text}
						disabled={busy}
						spellCheck={false}
						onChange={(e) => setText(e.target.value)}
						style={{ width: '100%' }}
					/>
					<div className="inline-actions spaced">
						<button disabled={busy || Boolean(status.lock_reason) || !status.fresh} onClick={() => apply()}>
							Save dashboard overrides
						</button>
						<button disabled={busy} onClick={download}>
							Download spot-config.json
						</button>
						<button
							disabled={busy}
							onClick={() =>
								void navigator.clipboard.writeText(text).then(
									() => announce('Configuration copied'),
									(e: unknown) => setNotice(errorMessage(e)),
								)
							}
						>
							Copy configuration
						</button>
					</div>
				</>
			) : null}
			<p className="feedback" role="status">
				{busy ? 'Applying settings…' : notice || task.error?.message}
			</p>
		</section>
	);
}
