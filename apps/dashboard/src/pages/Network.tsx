import { useState } from 'react';
import { useDashboard } from '../dashboard';
import { useOperation, useStatus } from '../queries';
import { DataList, Feedback, PageTitle, Panel } from '../components/common';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
const networkFeedback = {
	'network/apply': 'Check the address below, then Keep settings before the countdown ends.',
	'network/confirm': 'Network settings saved for future boots.',
	'network/revert': 'Previous connection restored.',
};
export default function NetworkPage() {
	const { announce } = useDashboard(),
		status = useStatus(),
		networkChange = useOperation<'network/apply' | 'network/confirm' | 'network/revert'>(),
		saveEndpoint = useOperation<'nt/endpoint'>(),
		standalone = useOperation<'standalone'>(),
		busy = networkChange.isPending,
		endpointBusy = saveEndpoint.isPending,
		network = status.network ?? {},
		endpoint = status.endpoint ?? {};
	const [mode, setMode] = useState(network.mode ?? 'automatic'),
		[address, setAddress] = useState(network.address ?? ''),
		[feedback, setFeedback] = useState('');

	const savedTarget = endpoint.configured || endpoint.team?.toString() || '',
		[target, setTarget] = useState(savedTarget),
		[byAddress, setByAddress] = useState(Boolean(endpoint.configured)),
		[lastTarget, setLastTarget] = useState(savedTarget);
	if (lastTarget !== savedTarget) {
		setLastTarget(savedTarget);
		setTarget(savedTarget);
		setByAddress(Boolean(endpoint.configured));
	}
	const endpointLocked = endpointBusy || Boolean(status.connected && status.lock_reason);

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

	const change = (variables: Parameters<typeof networkChange.mutate>[0]) =>
		networkChange.mutate(variables, {
			onSuccess: () => setFeedback(networkFeedback[variables.operation]),
			onError: (error) => {
				setRestore(true);
				setFeedback(error.message + ' If this page disconnected, open the new address or wait for rollback.');
			},
		});
	const pending = network.pending,
		pendingUrl = pending?.address ? `http://${pending.address.split('/')[0]}:${location.port || 80}/#network` : '';
	return (
		<>
			<PageTitle>Network</PageTitle>
			<div className="grid gap-6 md:grid-cols-2">
				<Panel title="Connection">
					<DataList
						id="connection-data"
						values={{
							'Robot endpoint': endpoint.configured || (endpoint.team ? `Team ${endpoint.team}` : 'Unavailable'),
							'NetworkTables server': status.connected ? 'Connected' : 'Disconnected',
							'Connection mode': endpoint.mode || 'NT4 client',
						}}
					/>
					<form
						className="flex flex-col gap-3"
						onSubmit={(e) => {
							e.preventDefault();
							saveEndpoint.mutate({
								operation: 'nt/endpoint',
								payload: byAddress ? { server: target.trim() } : { team: Number(target) },
							});
						}}
					>
						<Label htmlFor="nt-mode">Connect using</Label>
						<NativeSelect
							id="nt-mode"
							className="w-full"
							value={byAddress ? 'server' : 'team'}
							onChange={(e) => {
								setByAddress(e.target.value === 'server');
								setTarget('');
							}}
							disabled={endpointLocked}
						>
							<NativeSelectOption value="team">Team number</NativeSelectOption>
							<NativeSelectOption value="server">Server address</NativeSelectOption>
						</NativeSelect>
						<Label htmlFor="nt-target">{byAddress ? 'Server address' : 'Team number'}</Label>
						{byAddress ? (
							<Input
								id="nt-target"
								type="text"
								placeholder="10.5.81.2"
								pattern="[A-Za-z0-9.\-]{1,253}"
								required
								value={target}
								onChange={(e) => setTarget(e.target.value)}
								disabled={endpointLocked}
							/>
						) : (
							<Input
								id="nt-target"
								type="number"
								min="1"
								max="25599"
								step="1"
								required
								value={target}
								onChange={(e) => setTarget(e.target.value)}
								disabled={endpointLocked}
							/>
						)}
						<p>
							Saving reconnects NetworkTables. Use a server address for an NT4 server on a laptop or simulator. Jetson
							IP settings are configured below.
						</p>
						<Feedback>{status.connected ? status.lock_reason : ''}</Feedback>
						<Button type="submit" className="self-start" disabled={endpointLocked || !target}>
							Save robot endpoint
						</Button>
					</form>
					<Feedback id="endpoint-feedback">
						{saveEndpoint.isSuccess
							? 'Robot endpoint saved for future boots. Reconnecting NetworkTables.'
							: saveEndpoint.error?.message}
					</Feedback>
					<Button
						variant="outline"
						className="self-start"
						disabled={status.connected}
						onClick={() =>
							standalone.mutate(
								{ operation: 'standalone', payload: {} },
								{ onSuccess: () => announce('Standalone setup session started') },
							)
						}
					>
						{status.standalone ? 'Standalone setup active' : 'Begin standalone setup'}
					</Button>
					<Feedback id="page-feedback">{standalone.error?.message}</Feedback>
				</Panel>
				<Panel title="Link">
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
				</Panel>
			</div>
			<Panel title="Jetson address">
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
				<Feedback>
					{network.available
						? (status.connected && status.lock_reason) || ''
						: network.error || 'Install the Spot network helper to change Ethernet addresses.'}
				</Feedback>
				{pending ? (
					<div className="flex flex-col items-start gap-2">
						<p id="network-countdown" role="status">
							Testing network settings. Automatic rollback in {pending.remaining_s} seconds.{' '}
							{pendingUrl ? <a href={pendingUrl}>Open the new address</a> : 'Check the assigned DHCP address above.'}
						</p>
						<div className="flex gap-2">
							<Button
								disabled={busy}
								onClick={() => change({ operation: 'network/confirm', payload: { token: pending.token } })}
							>
								Keep settings
							</Button>
							<Button
								variant="outline"
								disabled={busy}
								onClick={() => change({ operation: 'network/revert', payload: { token: pending.token } })}
							>
								Revert now
							</Button>
						</div>
					</div>
				) : null}
				<form
					className="flex max-w-2xl flex-col gap-3"
					onSubmit={(e) => {
						e.preventDefault();
						change({
							operation: 'network/apply',
							payload: { mode, address: mode === 'static' ? address.trim() : '' },
						});
					}}
				>
					<Label htmlFor="network-mode">Address mode</Label>
					<NativeSelect
						id="network-mode"
						className="w-full"
						value={mode}
						disabled={busy || Boolean(pending)}
						onChange={(e) => setMode(e.target.value === 'static' ? 'static' : 'automatic')}
					>
						<NativeSelectOption value="automatic">Automatic (DHCP)</NativeSelectOption>
						<NativeSelectOption value="static">Static</NativeSelectOption>
					</NativeSelect>
					<Label htmlFor="network-address">IPv4 address / prefix</Label>
					<Input
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
					<Button
						className="self-start"
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
					</Button>
				</form>
				<p>
					Reconnect if the address changes, then choose Keep settings. Without confirmation, the previous connection
					returns automatically. Wi-Fi and the internet default route stay unchanged.
				</p>
				<Feedback id="network-feedback">{feedback}</Feedback>
			</Panel>
		</>
	);
}
