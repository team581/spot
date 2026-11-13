import { useState } from 'react';
import type { AddressMode, NetworkStatus, Settings } from '../api';
import { $api, queryClient, useNetwork, useSaveSettings, useSettings } from '../queries';
import { DataList, ErrorText, PageTitle, Panel } from '../components/common';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';

function SettingsForm({ settings }: { settings: Settings }) {
	const [team, setTeam] = useState(settings.team?.toString() ?? '');
	const [server, setServer] = useState(settings.nt_server ?? '');
	const save = useSaveSettings();
	return (
		<form
			className="flex flex-col gap-4"
			onSubmit={(e) => {
				e.preventDefault();
				save.mutate({
					body: { ...settings, nt_server: server.trim() || null, team: team.trim() ? Number(team) : null },
				});
			}}
		>
			<div className="flex flex-col gap-2">
				<Label htmlFor="team">Team number</Label>
				<Input
					id="team"
					inputMode="numeric"
					pattern="[0-9]*"
					value={team}
					onChange={(e) => {
						setTeam(e.target.value);
					}}
				/>
			</div>
			<div className="flex flex-col gap-2">
				<Label htmlFor="nt-server">NetworkTables server</Label>
				<Input
					id="nt-server"
					placeholder="Robot address from the team number"
					value={server}
					onChange={(e) => {
						setServer(e.target.value);
					}}
				/>
			</div>
			<div className="flex items-center gap-3">
				<Button type="submit" disabled={save.isPending}>
					Save
				</Button>
				<ErrorText error={save.error} />
			</div>
		</form>
	);
}

function EthernetForm({
	network,
	apply,
}: {
	network: NetworkStatus;
	apply: (mode: AddressMode, address: string) => void;
}) {
	const [mode, setMode] = useState(network.mode);
	const [address, setAddress] = useState(network.address);
	return (
		<form
			className="flex flex-col gap-4"
			onSubmit={(e) => {
				e.preventDefault();
				apply(mode, address.trim());
			}}
		>
			<div className="flex flex-col gap-2">
				<Label htmlFor="mode">Addressing</Label>
				<NativeSelect
					id="mode"
					className="w-full"
					value={mode}
					onChange={(e) => {
						const { value } = e.target;
						if (value === 'automatic' || value === 'static') {
							setMode(value);
						}
					}}
				>
					<NativeSelectOption value="automatic">Automatic (DHCP)</NativeSelectOption>
					<NativeSelectOption value="static">Static</NativeSelectOption>
				</NativeSelect>
			</div>
			{mode === 'static' ? (
				<div className="flex flex-col gap-2">
					<Label htmlFor="address">Static address</Label>
					<Input
						id="address"
						placeholder="10.5.81.11/24"
						value={address}
						onChange={(e) => {
							setAddress(e.target.value);
						}}
					/>
				</div>
			) : null}
			<div>
				<Button type="submit" disabled={mode === 'static' && !address.trim()}>
					Try change
				</Button>
			</div>
		</form>
	);
}

const onSuccess = (data: NetworkStatus) =>
	queryClient.setQueryData($api.queryOptions('get', '/api/network').queryKey, data);

function Ethernet() {
	const { data: network, error } = useNetwork();
	const apply = $api.useMutation('post', '/api/network', { onSuccess });
	const confirm = $api.useMutation('post', '/api/network/confirm', { onSuccess });
	const revert = $api.useMutation('post', '/api/network/revert', { onSuccess });
	if (!network) {
		return <Panel title="Ethernet">{error ? <ErrorText error={error} /> : 'Loading…'}</Panel>;
	}
	const { pending } = network;
	return (
		<Panel title="Ethernet">
			<DataList
				values={{
					Link: network.connected ? 'Connected' : 'No cable',
					Addressing: network.mode === 'static' ? `Static ${network.address}` : 'Automatic',
					Addresses: network.addresses.join(', ') || '—',
					'Maintenance address': network.maintenance_address,
				}}
			/>
			{pending ? (
				<Alert>
					<AlertTitle>
						Trying {pending.mode === 'static' ? `static ${pending.address}` : 'automatic addressing'}
					</AlertTitle>
					<AlertDescription>
						Rolls back in {pending.remaining_s} s unless confirmed. If this page stops responding, reconnect at{' '}
						{network.maintenance_address}.
					</AlertDescription>
					<AlertAction className="flex gap-2">
						<Button
							size="sm"
							onClick={() => {
								confirm.mutate({});
							}}
						>
							Confirm
						</Button>
						<Button
							size="sm"
							variant="outline"
							onClick={() => {
								revert.mutate({});
							}}
						>
							Revert
						</Button>
					</AlertAction>
				</Alert>
			) : (
				<EthernetForm
					key={network.mode + network.address}
					network={network}
					apply={(mode, address) => {
						apply.mutate({ body: mode === 'static' ? { address, mode } : { mode } });
					}}
				/>
			)}
			<ErrorText error={apply.error ?? confirm.error ?? revert.error} />
		</Panel>
	);
}

export default function Network() {
	const { data: settings, error } = useSettings();
	return (
		<>
			<PageTitle>Network</PageTitle>
			<div className="grid max-w-5xl gap-6 lg:grid-cols-2">
				<Panel title="Robot">
					<ErrorText error={error} />
					{settings ? <SettingsForm key={JSON.stringify(settings)} settings={settings} /> : null}
				</Panel>
				<Ethernet />
			</div>
		</>
	);
}
