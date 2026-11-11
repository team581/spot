import { useStatus, useSystem } from '../queries';
import { DataList, ErrorText, fmt, PageTitle, Panel, StateBadge } from '../components/common';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

const percent = (value: number | null | undefined) => (value == null ? '—' : fmt(value, 0) + '%');

function uptime(seconds: number | null | undefined) {
	if (seconds == null) return '—';
	const h = Math.floor(seconds / 3600),
		m = Math.floor((seconds % 3600) / 60);
	return h ? `${h} h ${m} min` : `${m} min`;
}

export default function System() {
	const { data: system, error } = useSystem(),
		cameras = useStatus().data?.cameras ?? [];
	return (
		<>
			<PageTitle>System</PageTitle>
			<ErrorText error={error} />
			<div className="grid max-w-5xl gap-6 lg:grid-cols-2">
				<Panel title="Jetson">
					<DataList
						values={{
							CPU: percent(system?.cpu_percent),
							GPU: percent(system?.gpu_percent),
							Memory: percent(system?.memory_percent),
							Disk: percent(system?.disk_percent),
							Uptime: uptime(system?.uptime_s),
						}}
					/>
				</Panel>
				<Panel title="Temperatures">
					{system?.temperatures.length ? (
						<DataList values={Object.fromEntries(system.temperatures.map((t) => [t.name, fmt(t.celsius) + ' °C']))} />
					) : (
						<p className="text-sm text-muted-foreground">No temperature sensors</p>
					)}
				</Panel>
				<Panel title="Cameras" className="lg:col-span-2">
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Camera</TableHead>
								<TableHead>State</TableHead>
								<TableHead className="text-right">FPS</TableHead>
								<TableHead className="text-right">Capture FPS</TableHead>
								<TableHead className="text-right">Dropped frames</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{cameras.map((c) => (
								<TableRow key={c.name}>
									<TableCell>{c.name}</TableCell>
									<TableCell>
										<StateBadge state={c.state} />
									</TableCell>
									<TableCell className="text-right">{fmt(c.fps)}</TableCell>
									<TableCell className="text-right">{fmt(c.capture_fps)}</TableCell>
									<TableCell className="text-right">{c.dropped_frames}</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				</Panel>
			</div>
		</>
	);
}
