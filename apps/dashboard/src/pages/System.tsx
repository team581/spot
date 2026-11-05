import type { OperationName, OperationPayload } from '../api';
import { useState } from 'react';
import RobotConfiguration from '../components/RobotConfiguration';
import { useDashboard, errorMessage } from '../dashboard';
import { api } from '../api';
import { DataList, age, date, fmt } from '../components/common';
export default function System() {
	const { status: s, serviceError, mutate, announce } = useDashboard(),
		m = s.system ?? {},
		r = s.software;
	const [error, setError] = useState('');
	const run = async <N extends OperationName>(operation: N, payload: OperationPayload<N>, message: string) => {
		try {
			await mutate(operation, payload);
			announce(message);
		} catch (e) {
			setError(errorMessage(e));
		}
	};
	const download = async (path: string, name: string) => {
		try {
			const result = await api(path),
				url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })),
				link = document.createElement('a');
			link.href = url;
			link.download = name;
			link.click();
			setTimeout(() => URL.revokeObjectURL(url), 1000);
		} catch (e) {
			setError(errorMessage(e));
		}
	};
	const stats = {
		CPU: Number.isFinite(m.cpu_percent) ? `${fmt(m.cpu_percent, 0)}%` : '—',
		GPU: Number.isFinite(m.gpu_percent) ? `${fmt(m.gpu_percent, 0)}%` : '—',
		Temperature: Number.isFinite(m.temperature_c) ? `${fmt(m.temperature_c, 0)} °C` : '—',
		Memory: Number.isFinite(m.memory_used_gb) ? `${fmt(m.memory_used_gb)} / ${fmt(m.memory_total_gb)} GB` : '—',
		Uptime: age(s.uptime_s),
	};
	const faults = [
		serviceError,
		...(s.faults ?? []),
		...s.cameras.filter((c) => c.fault).map((c) => c.name + ': ' + c.fault),
	].filter(Boolean);
	return (
		<>
			<h1>System</h1>
			<div className="panel stats">
				{Object.entries(stats).map(([name, value]) => (
					<div className="stat" key={name}>
						<strong>{value}</strong>
						<small>{name}</small>
					</div>
				))}
			</div>
			<div className="system-grid">
				<RobotConfiguration />
				<section className="panel">
					<h2>Camera pipelines</h2>
					<div className="table-scroll">
						<table>
							<thead>
								<tr>
									<th>Camera</th>
									<th>Capture / detect</th>
									<th>Backend</th>
									<th>Published / withheld</th>
									<th>Drops</th>
									<th>Frame age</th>
								</tr>
							</thead>
							<tbody>
								{s.cameras.map((c) => (
									<tr key={c.identity}>
										<td>{c.name}</td>
										<td>
											{c.connected
												? `${fmt(c.metrics?.fps_capture, 0)} / ${(c.metrics?.detect_age_s ?? Infinity) <= 0.5 ? fmt(c.metrics?.fps_detect, 0) : '—'} FPS`
												: '—'}
										</td>
										<td>
											{c.processing?.backend || 'Unavailable'}
											{c.processing?.overload_reduction ? ' · load' : ''}
										</td>
										<td>
											{c.metrics?.published ?? '—'} / {c.metrics?.withheld ?? '—'}
											<br />
											<small>{age(c.metrics?.publish_age_s)}</small>
										</td>
										<td>
											{c.metrics?.overwritten_before_processing ?? '—'} / {c.metrics?.driver_sequence_gaps ?? '—'}
										</td>
										<td>{age(c.age_s)}</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				</section>
				<section className="panel">
					<h2>Software</h2>
					<DataList
						id="software-data"
						values={{
							'NixOS system': r.system_path || 'Unavailable',
							'Application package': r.package_path || 'Unavailable',
							'Configuration revision': r.configuration_revision || 'Unavailable',
							Version: r.version || 'Unavailable',
							'CUDA build': r.native_cuda == null ? 'Unavailable' : r.native_cuda ? 'Yes' : 'No',
							Started: date(r.process_started_at),
						}}
					/>
				</section>
				<section className="panel">
					<h2>USB devices</h2>
					{s.cameras.map((c) => (
						<p key={c.identity}>
							<strong>{c.name}</strong>
							<br />
							<small>
								{c.topology || 'Missing'} · {c.capture_node || 'No capture node'}
								<br />
								Saved port slot {c.display_id}
								{c.unique_serial ? ' · serial ' + c.serial : ' · duplicate/missing serial'}
							</small>
						</p>
					))}
				</section>
				<section className="panel">
					<h2>Clock and startup</h2>
					<DataList
						values={{
							Clock: s.clock.state || 'Unavailable',
							Offset: `${s.clock.offset_us ?? '—'} µs`,
							...Object.fromEntries(
								Object.entries(s.startup ?? {}).map(([key, value]) => [key.replaceAll('_', ' '), age(value)]),
							),
						}}
					/>
				</section>
				<section className="panel wide">
					<h2>Faults and support</h2>
					{faults.length ? (
						faults.map((f) => (
							<p className="warning" key={f}>
								{f}
							</p>
						))
					) : (
						<p>No active faults reported</p>
					)}
					<div className="inline-actions spaced">
						<button onClick={() => void download('/api/support', 'spot-support.json')}>Export support bundle</button>
						<button onClick={() => void download('/api/calibrations', 'spot-calibrations.json')}>
							Download calibration results
						</button>
						<button onClick={() => void download('/api/configuration', 'spot-state.json')}>Export saved setup</button>
						<label>
							<input
								type="file"
								accept="application/json,.json"
								onChange={async (e) => {
									const file = e.target.files?.[0];
									if (!file) return;
									if (file.size > 2 * 1024 * 1024) {
										setError('Configuration exceeds 2 MiB import bound');
										return;
									}
									try {
										const document = JSON.parse(await file.text());
										await run('configuration/import', { document, revision: s.revision }, 'Calibration data imported');
									} catch (error) {
										setError(errorMessage(error));
									}
								}}
							/>{' '}
							Import saved setup
						</label>
						<button
							onClick={() =>
								void run('debug/record', { seconds: 10, revision: s.revision }, 'Bounded diagnostics recording started')
							}
						>
							Record 10 s diagnostics
						</button>
					</div>
					<p id="page-feedback" className="feedback">
						{error}
					</p>
				</section>
			</div>
		</>
	);
}
