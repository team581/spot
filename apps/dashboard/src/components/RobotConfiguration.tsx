import { useState } from 'react';
import { api } from '../api';
import { errorMessage, useDashboard } from '../dashboard';

export default function RobotConfiguration() {
	const { status, mutate, announce } = useDashboard();
	const [text, setText] = useState('');
	const [revision, setRevision] = useState('');
	const [error, setError] = useState('');
	const [busy, setBusy] = useState(false);

	const load = async (defaults = false) => {
		setBusy(true);
		setError('');
		try {
			// Keep the revision observed before the request; a concurrent edit must conflict.
			const expected = status.revision;
			const settings = await api(defaults ? '/api/robot-defaults' : '/api/robot-config');
			setText(JSON.stringify(settings, null, 2));
			setRevision(expected);
		} catch (e) {
			setError(errorMessage(e));
		} finally {
			setBusy(false);
		}
	};
	const apply = async () => {
		setBusy(true);
		setError('');
		try {
			const document = JSON.parse(text) as Record<string, unknown>;
			const job = await mutate('configure', { document, revision });
			setRevision(job.revision);
			announce('Dashboard overrides saved.');
		} catch (e) {
			setError(errorMessage(e));
		} finally {
			setBusy(false);
		}
	};
	const clear = async (path = '') => {
		setBusy(true);
		setError('');
		try {
			const job = await mutate('clear-overrides', { path, revision: status.revision });
			setRevision(job.revision);
			if (text) setText(JSON.stringify(await api('/api/robot-config'), null, 2));
			announce(path ? 'Override cleared' : 'All overrides cleared');
		} catch (error) {
			setError(errorMessage(error));
		} finally {
			setBusy(false);
		}
	};
	const download = () => {
		try {
			const contents = JSON.stringify(JSON.parse(text), null, 2) + '\n';
			const url = URL.createObjectURL(new Blob([contents], { type: 'application/json' }));
			const link = document.createElement('a');
			link.href = url;
			link.download = 'spot-config.json';
			link.click();
			setTimeout(() => URL.revokeObjectURL(url), 1000);
		} catch (e) {
			setError(errorMessage(e));
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
								<button disabled={busy || Boolean(status.lock_reason)} onClick={() => void clear(path)}>
									Clear override
								</button>
							</li>
						))}
					</ul>
					<button disabled={busy || Boolean(status.lock_reason)} onClick={() => void clear()}>
						Clear all overrides
					</button>
				</>
			) : null}
			<p>
				Download the effective configuration and replace <code>src/main/deploy/spot-config.json</code> in the robot
				project. Calibration results can be copied between this file and standalone calibration exports.
			</p>
			<div className="inline-actions spaced">
				<button disabled={busy || !status.fresh} onClick={() => void load()}>
					Read current configuration
				</button>
				<button disabled={busy || !status.fresh} onClick={() => void load(true)}>
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
								setError('Configuration exceeds 256 KiB');
								return;
							}
							try {
								const expected = status.revision;
								setText(JSON.stringify(JSON.parse(await file.text()), null, 2));
								setRevision(expected);
								setError('');
							} catch (error) {
								setError(errorMessage(error));
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
						<button disabled={busy || Boolean(status.lock_reason) || !status.fresh} onClick={() => void apply()}>
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
									(e: unknown) => setError(errorMessage(e)),
								)
							}
						>
							Copy configuration
						</button>
					</div>
				</>
			) : null}
			<p className="feedback" role="status">
				{busy ? 'Applying settings…' : error}
			</p>
		</section>
	);
}
