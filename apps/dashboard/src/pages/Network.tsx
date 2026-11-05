import type { OperationPayload } from '../api';
import { useState } from 'react';
import { useDashboard, errorMessage } from '../dashboard';
import { DataList } from '../components/common';
export default function NetworkPage() {
	const { status, mutate, announce } = useDashboard(),
		network = status.network ?? {},
		endpoint = status.endpoint ?? {};
	const [mode, setMode] = useState(network.mode ?? 'automatic'),
		[address, setAddress] = useState(network.address ?? ''),
		[busy, setBusy] = useState(false),
		[feedback, setFeedback] = useState(''),
		[error, setError] = useState('');

	const [team, setTeam] = useState(endpoint.team?.toString() ?? ''),
		[lastTeam, setLastTeam] = useState(endpoint.team),
		[teamBusy, setTeamBusy] = useState(false),
		[teamFeedback, setTeamFeedback] = useState('');
	if (lastTeam !== endpoint.team) {
		setLastTeam(endpoint.team);
		setTeam(endpoint.team?.toString() ?? '');
	}

	const [restore, setRestore] = useState(true),
		[lastPending, setLastPending] = useState('');
	const token = network.pending?.token ?? '';
	if (lastPending !== token) {
		setLastPending(token);
		if (lastPending && !token) setRestore(true);
	}
	if (restore && !busy && !network.pending) {
		if (network.available && network.mode) {
			setMode(network.mode);
			setAddress(network.address ?? '');
			setRestore(false);
		}
	}

	async function change<A extends 'apply' | 'confirm' | 'revert'>(
		operation: A,
		payload: OperationPayload<`network/${A}`>,
	) {
		setBusy(true);
		try {
			await mutate(`network/${operation}`, payload);
			setFeedback(
				operation === 'apply'
					? 'Check the address below, then Keep settings before the countdown ends.'
					: operation === 'confirm'
						? 'Network settings saved for future boots.'
						: 'Previous connection restored.',
			);
		} catch (e) {
			setRestore(true);
			setFeedback(errorMessage(e) + ' If this page disconnected, open the new address or wait for rollback.');
		} finally {
			setBusy(false);
		}
	}
	const pending = network.pending,
		target = pending?.address ? `http://${pending.address.split('/')[0]}:${location.port || 80}/#network` : '';
	return (
		<>
			<h1>Network</h1>
			<div className="two-columns">
				<section className="panel">
					<h2>Connection</h2>
					<DataList
						id="connection-data"
						values={{
							'Robot endpoint': endpoint.configured || (endpoint.team ? `Team ${endpoint.team}` : 'Unavailable'),
							'NetworkTables server': status.connected ? 'Connected' : 'Disconnected',
							'Connection mode': endpoint.mode || 'NT4 client',
						}}
					/>
					<form
						onSubmit={async (e) => {
							e.preventDefault();
							setTeamBusy(true);
							try {
								await mutate('nt/team', { team: Number(team) });
								setTeamFeedback('Team number saved for future boots. Reconnecting NetworkTables.');
							} catch (e) {
								setTeamFeedback(errorMessage(e));
							} finally {
								setTeamBusy(false);
							}
						}}
					>
						<label htmlFor="nt-team">Team number</label>
						<input
							id="nt-team"
							type="number"
							min="1"
							max="25599"
							step="1"
							required
							value={team}
							onChange={(e) => setTeam(e.target.value)}
							disabled={teamBusy || Boolean(status.connected && status.lock_reason)}
						/>
						<p>Changing the team number reconnects NetworkTables. Jetson IP settings are configured below.</p>
						<p className="lock">{status.connected ? status.lock_reason : ''}</p>
						<button type="submit" disabled={teamBusy || !team || Boolean(status.connected && status.lock_reason)}>
							Save team number
						</button>
					</form>
					<p id="team-feedback" className="feedback" role="status">
						{teamFeedback}
					</p>
					<button
						disabled={status.connected}
						onClick={async () => {
							try {
								await mutate('standalone', {});
								announce('Standalone setup session started');
							} catch (e) {
								setError(errorMessage(e));
							}
						}}
					>
						{status.standalone ? 'Standalone setup active' : 'Begin standalone setup'}
					</button>
					<p id="page-feedback" className="feedback">
						{error}
					</p>
				</section>
				<section className="panel">
					<h2>Link</h2>
					<DataList
						values={{
							NetworkTables: status.connected ? 'Connected' : 'Disconnected',
							'Local addresses': endpoint.local_addresses?.join(', ') || 'Unavailable',
							Synchronization: status.clock.state || 'Unavailable',
							Profile: status.fresh
								? 'Current robot session'
								: status.has_configuration
									? 'Cached configuration'
									: 'Unavailable',
						}}
					/>
				</section>
			</div>
			<section className="panel spaced">
				<h2>Jetson address</h2>
				<p>
					{network.hostname ? (
						<>
							Find Spot on this local network:{' '}
							<a href={`http://${network.hostname}:${location.port || 80}/`}>{network.hostname}</a>.
						</>
					) : (
						'Local-name discovery is unavailable. Use one of the current IP addresses below.'
					)}
				</p>
				<p>Either Ethernet port works. Both ports share these addresses and settings.</p>
				<DataList
					values={{
						'Current addresses': network.addresses?.join(', ') || 'Unavailable',
						'Maintenance address': network.maintenance_address || 'Unavailable',
					}}
				/>
				<p className="lock">
					{network.available
						? (status.connected && status.lock_reason) || ''
						: network.error || 'Install the Spot network helper to change Ethernet addresses.'}
				</p>
				{pending ? (
					<div>
						<p id="network-countdown" role="status">
							Testing network settings. Automatic rollback in {pending.remaining_s} seconds.{' '}
							{target ? <a href={target}>Open the new address</a> : 'Check the assigned DHCP address above.'}
						</p>
						<button disabled={busy} onClick={() => void change('confirm', { token: pending.token })}>
							Keep settings
						</button>{' '}
						<button disabled={busy} onClick={() => void change('revert', { token: pending.token })}>
							Revert now
						</button>
					</div>
				) : null}
				<form
					onSubmit={(e) => {
						e.preventDefault();
						void change('apply', {
							mode,
							address: mode === 'static' ? address.trim() : '',
						});
					}}
				>
					<label htmlFor="network-mode">Address mode</label>
					<select
						id="network-mode"
						value={mode}
						disabled={busy || Boolean(pending)}
						onChange={(e) => setMode(e.target.value === 'static' ? 'static' : 'automatic')}
					>
						<option value="automatic">Automatic (DHCP)</option>
						<option value="static">Static</option>
					</select>
					<label htmlFor="network-address">IPv4 address / prefix</label>
					<input
						id="network-address"
						placeholder="10.5.81.11/24"
						autoComplete="off"
						value={address}
						onChange={(e) => setAddress(e.target.value)}
						disabled={mode !== 'static' || busy || Boolean(pending)}
					/>
					<p>
						Automatic needs a DHCP server. A direct roboRIO cable usually needs Static. The maintenance address stays
						available through either port.
					</p>
					<button
						className="primary"
						type="submit"
						disabled={
							busy ||
							!network.available ||
							(mode === 'static' && !address.trim()) ||
							Boolean(pending) ||
							Boolean(status.connected && status.lock_reason)
						}
					>
						Apply for 90 seconds
					</button>
				</form>
				<p>
					Reconnect if the address changes, then choose Keep settings. Without confirmation, the previous connection
					returns automatically. Wi-Fi and the internet default route stay unchanged.
				</p>
				<p id="network-feedback" className="feedback">
					{feedback}
				</p>
			</section>
		</>
	);
}
