import { useMutation } from '@tanstack/react-query';
import { useDashboard, useServiceError } from '../dashboard';
import { api } from '../api';
import { DataList, Feedback, PageTitle, Panel, age, date, fmt, saveJson } from '../components/common';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useOperation, useStatus } from '../queries';
export default function System() {
	const { announce } = useDashboard(),
		s = useStatus(),
		serviceError = useServiceError(),
		m = s.system ?? {},
		r = s.software;
	const operation = useOperation<'debug/record'>();
	const download = useMutation({
		mutationFn: async ({ path, name }: { path: string; name: string }) => saveJson(await api(path), name),
	});
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
			<PageTitle>System</PageTitle>
			<div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
				{Object.entries(stats).map(([name, value]) => (
					<Card key={name} size="sm" className="gap-1 px-3">
						<strong className="font-heading text-2xl font-semibold">{value}</strong>
						<small className="text-muted-foreground">{name}</small>
					</Card>
				))}
			</div>
			<div className="grid gap-6 lg:grid-cols-2">
				<Panel title="Camera pipelines">
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Camera</TableHead>
								<TableHead>Capture / detect</TableHead>
								<TableHead>Backend</TableHead>
								<TableHead>Published / withheld</TableHead>
								<TableHead>Drops</TableHead>
								<TableHead>Frame age</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{s.cameras.map((c) => (
								<TableRow key={c.identity}>
									<TableCell>{c.name}</TableCell>
									<TableCell>
										{c.connected
											? `${fmt(c.metrics?.fps_capture, 0)} / ${(c.metrics?.detect_age_s ?? Infinity) <= 0.5 ? fmt(c.metrics?.fps_detect, 0) : '—'} FPS`
											: '—'}
									</TableCell>
									<TableCell>
										{c.processing?.backend || 'Unavailable'}
										{c.processing?.overload_reduction ? ' · load' : ''}
									</TableCell>
									<TableCell>
										{c.metrics?.published ?? '—'} / {c.metrics?.withheld ?? '—'}
										<br />
										<small className="text-muted-foreground">{age(c.metrics?.publish_age_s)}</small>
									</TableCell>
									<TableCell>
										{c.metrics?.overwritten_before_processing ?? '—'} / {c.metrics?.driver_sequence_gaps ?? '—'}
									</TableCell>
									<TableCell>{age(c.age_s)}</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				</Panel>
				<Panel title="Software">
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
				</Panel>
				<Panel title="USB devices">
					{s.cameras.map((c) => (
						<p key={c.identity}>
							<strong>{c.name}</strong>
							<br />
							<small className="text-muted-foreground">
								{c.topology || 'Missing'} · {c.capture_node || 'No capture node'}
								<br />
								Saved port slot {c.display_id}
								{c.unique_serial ? ' · serial ' + c.serial : ' · duplicate/missing serial'}
							</small>
						</p>
					))}
				</Panel>
				<Panel title="Clock and startup">
					<DataList
						values={{
							Clock: s.clock.state || 'Unavailable',
							Offset: `${s.clock.offset_us ?? '—'} µs`,
							...Object.fromEntries(
								Object.entries(s.startup ?? {}).map(([key, value]) => [key.replaceAll('_', ' '), age(value)]),
							),
						}}
					/>
				</Panel>
				<Panel title="Faults and support" className="lg:col-span-2">
					{faults.length ? (
						faults.map((f) => (
							<p className="text-warning" key={f}>
								{f}
							</p>
						))
					) : (
						<p>No active faults reported</p>
					)}
					<div className="flex flex-wrap items-center gap-2">
						<Button
							variant="outline"
							onClick={() => download.mutate({ path: '/api/support', name: 'spot-support.json' })}
						>
							Export support bundle
						</Button>
						<Button
							variant="outline"
							onClick={() =>
								operation.mutate(
									{ operation: 'debug/record', payload: { seconds: 10, revision: s.revision } },
									{ onSuccess: () => announce('Bounded diagnostics recording started') },
								)
							}
						>
							Record 10 s diagnostics
						</Button>
					</div>
					<Feedback id="page-feedback">{operation.error?.message || download.error?.message}</Feedback>
				</Panel>
			</div>
		</>
	);
}
