import type { OperationName, OperationPayload } from '../api';
import { useState } from 'react';
import { useDashboard, errorMessage } from '../dashboard';
import { availableCameraNames } from '../state/editing';
import { Feed } from '../components/Feed';
import { CameraSelector } from '../components/common';
import type { Camera } from '../types';
export default function CameraName({ camera: c }: { camera: Camera }) {
	const { status, mutate, announce } = useDashboard(),
		available = availableCameraNames(status.names, status.cameras, c.identity);
	const [choice, setChoice] = useState(''),
		[confirmed, setConfirmed] = useState(false),
		[busy, setBusy] = useState(false),
		[error, setError] = useState('');
	const run = async <N extends OperationName>(operation: N, payload: OperationPayload<N>) => {
		setBusy(true);
		try {
			await mutate(operation, payload);
			if (operation === 'device/name') announce('Camera renamed');
		} catch (e) {
			setError(errorMessage(e));
		} finally {
			setBusy(false);
		}
	};
	return (
		<>
			<h1 id="camera-title">{c.name}</h1>
			<CameraSelector cameras={status.cameras} id={c.identity} />
			<div className="name-layout">
				<Feed id={c.identity} />
				<section className="panel">
					<h2>Camera name</h2>
					<p className="warning">⚠ Not configured in code</p>
					<label htmlFor="camera-name">Name</label>
					<select
						id="camera-name"
						value={available.includes(choice) ? choice : (available[0] ?? '')}
						onChange={(e) => setChoice(e.target.value)}
					>
						{available.length ? (
							available.map((name) => <option key={name}>{name}</option>)
						) : (
							<option value="">No names available in robot code</option>
						)}
					</select>
					<label className="spaced">
						<input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> This preview
						matches the physical camera
					</label>
					<button
						id="rename"
						className="primary"
						disabled={busy || Boolean(status.lock_reason) || !c.connected || !available.length || !confirmed}
						onClick={() =>
							void run('device/name', {
								identity: c.identity,
								name: available.includes(choice) ? choice : available[0],
								revision: status.revision,
							})
						}
					>
						Rename
					</button>
					<hr />
					<p>Use this camera without a robot profile for tuning and calibration.</p>
					<button
						disabled={busy}
						onClick={() => void run('device/setup', { identity: c.identity, revision: status.revision })}
					>
						Open standalone camera setup
					</button>
					<p id="naming-lock" className="lock">
						{status.lock_reason ||
							(status.fresh
								? 'Confirm this preview matches the physical camera'
								: 'Cached code names · standalone setup')}
					</p>
					<p id="page-feedback" className="feedback">
						{error}
					</p>
					<a href="/docs/operator/cameras/#assign-cameras">Configure camera names in robot code</a>
				</section>
			</div>
		</>
	);
}
