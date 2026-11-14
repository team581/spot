import { useForm, useSelector } from '@tanstack/react-form';
import { z } from 'zod';
import type { AddressMode, NetworkStatus, Settings } from '../api';
import { $api, queryClient, useNetwork, useSaveSettings, useSettings } from '../queries';
import { DataList, ErrorText, PageTitle, Panel } from '../components/common';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';

const settingsSchema = z.object({
	team: z
		.string()
		.trim()
		.regex(/^\d*$/, 'Enter a team number, or leave it blank.')
		.transform((team) => (team ? Number(team) : null)),
	server: z
		.string()
		.trim()
		.transform((server) => server || null),
});

function SettingsForm({ settings }: { settings: Settings }) {
	const save = useSaveSettings();
	const form = useForm({
		defaultValues: { team: settings.team?.toString() ?? '', server: settings.nt_server ?? '' },
		validators: { onSubmit: settingsSchema },
		onSubmit: ({ value }) => {
			const { team, server } = settingsSchema.parse(value);
			save.mutate({ body: { ...settings, nt_server: server, team } });
		},
	});
	return (
		<form
			onSubmit={(e) => {
				e.preventDefault();
				void form.handleSubmit();
			}}
		>
			<FieldGroup>
				<form.Field name="team">
					{(field) => {
						const isInvalid = field.state.meta.isTouched && !field.state.meta.isValid;
						return (
							<Field data-invalid={isInvalid}>
								<FieldLabel htmlFor={field.name}>Team number</FieldLabel>
								<Input
									id={field.name}
									name={field.name}
									inputMode="numeric"
									value={field.state.value}
									onBlur={field.handleBlur}
									onChange={(e) => {
										field.handleChange(e.target.value);
									}}
									aria-invalid={isInvalid}
								/>
								{isInvalid ? <FieldError errors={field.state.meta.errors} /> : null}
							</Field>
						);
					}}
				</form.Field>
				<form.Field name="server">
					{(field) => {
						const isInvalid = field.state.meta.isTouched && !field.state.meta.isValid;
						return (
							<Field data-invalid={isInvalid}>
								<FieldLabel htmlFor={field.name}>NetworkTables server</FieldLabel>
								<Input
									id={field.name}
									name={field.name}
									placeholder="Robot address from the team number"
									value={field.state.value}
									onBlur={field.handleBlur}
									onChange={(e) => {
										field.handleChange(e.target.value);
									}}
									aria-invalid={isInvalid}
								/>
								{isInvalid ? <FieldError errors={field.state.meta.errors} /> : null}
							</Field>
						);
					}}
				</form.Field>
				<Field orientation="horizontal">
					<Button type="submit" disabled={save.isPending}>
						Save
					</Button>
					<ErrorText error={save.error} />
				</Field>
			</FieldGroup>
		</form>
	);
}

const ethernetSchema = z
	.object({ mode: z.enum(['automatic', 'static']), address: z.string().trim() })
	.refine(({ mode, address }) => mode === 'automatic' || z.ipv4().safeParse(address).success, {
		message: 'Enter an IPv4 address, like 10.5.81.12.',
		path: ['address'],
	});

function EthernetForm({
	network,
	apply,
}: {
	network: NetworkStatus;
	apply: (mode: AddressMode, address: string) => void;
}) {
	const form = useForm({
		defaultValues: { mode: network.mode, address: network.address },
		validators: { onSubmit: ethernetSchema },
		onSubmit: ({ value }) => {
			const { mode, address } = ethernetSchema.parse(value);
			apply(mode, address);
		},
	});
	const mode = useSelector(form.store, (state) => state.values.mode);
	return (
		<form
			onSubmit={(e) => {
				e.preventDefault();
				void form.handleSubmit();
			}}
		>
			<FieldGroup>
				<form.Field name="mode">
					{(field) => (
						<Field>
							<FieldLabel htmlFor={field.name}>Addressing</FieldLabel>
							<NativeSelect
								id={field.name}
								name={field.name}
								className="w-full"
								value={field.state.value}
								onBlur={field.handleBlur}
								onChange={(e) => {
									const { value } = e.target;
									if (value === 'automatic' || value === 'static') {
										field.handleChange(value);
									}
								}}
							>
								<NativeSelectOption value="automatic">Automatic (DHCP)</NativeSelectOption>
								<NativeSelectOption value="static">Static</NativeSelectOption>
							</NativeSelect>
						</Field>
					)}
				</form.Field>
				{mode === 'static' ? (
					<form.Field name="address">
						{(field) => {
							const isInvalid = field.state.meta.isTouched && !field.state.meta.isValid;
							return (
								<Field data-invalid={isInvalid}>
									<FieldLabel htmlFor={field.name}>Static address</FieldLabel>
									<Input
										id={field.name}
										name={field.name}
										placeholder="10.5.81.12"
										value={field.state.value}
										onBlur={field.handleBlur}
										onChange={(e) => {
											field.handleChange(e.target.value);
										}}
										aria-invalid={isInvalid}
									/>
									{isInvalid ? <FieldError errors={field.state.meta.errors} /> : null}
								</Field>
							);
						}}
					</form.Field>
				) : null}
				<Field orientation="horizontal">
					<Button type="submit">Try change</Button>
				</Field>
			</FieldGroup>
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
