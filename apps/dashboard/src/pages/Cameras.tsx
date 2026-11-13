import { Link } from '@tanstack/react-router';
import { useConfig, useDevices, useStatus } from '../queries';
import { useAllDetections } from '../live';
import { fmt, PageTitle, Panel, StateBadge } from '../components/common';
import { Field3D } from '../components/Field3D';
import { LiveView } from '../components/LiveView';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

/** Live estimates, mounts, and seen tags from every camera on the field. */
function Field() {
	const view = useConfig().data,
		config = view?.config,
		cameras = Object.entries(config?.cameras ?? {}),
		detections = useAllDetections(cameras.map(([name]) => name));
	if (!config) return null;
	return (
		<Panel title="Field">
			<Field3D
				field={view.field_layout}
				cameras={cameras.map(([name, camera]) => ({ name, config: camera, detections: detections.get(name) }))}
			/>
		</Panel>
	);
}

export default function Cameras() {
	const cameras = useStatus().data?.cameras ?? [],
		unassigned = useDevices().data?.filter((d) => !d.camera) ?? [];
	return (
		<>
			<PageTitle
				action={
					<Button variant="outline" render={<Link to="/devices" />}>
						Assign devices
					</Button>
				}
			>
				Cameras
			</PageTitle>
			{cameras.length ? (
				<div className="grid gap-6 md:grid-cols-2">
					{cameras.map((c) => (
						<Link
							key={c.name}
							to="/cameras/$name"
							params={{ name: c.name }}
							className="group/tile rounded-xl text-foreground no-underline"
						>
							<Card className="gap-0 py-0 transition-shadow group-hover/tile:ring-foreground/30">
								<header className="flex items-center justify-between gap-2 px-4 py-3">
									<strong className="font-heading text-base">{c.name}</strong>
									<StateBadge state={c.state} />
								</header>
								<LiveView camera={c.name} className="rounded-none" />
								<div className="flex justify-between gap-2 px-4 py-3 text-sm">
									<span>{c.mode}</span>
									<span className="font-semibold">{fmt(c.fps, 0)} FPS</span>
								</div>
							</Card>
						</Link>
					))}
				</div>
			) : (
				<Panel title="No cameras configured" className="max-w-2xl">
					<p className="text-sm">
						Add cameras to the robot config, or <Link to="/devices">assign a connected device</Link> to a camera name.
					</p>
				</Panel>
			)}
			{cameras.length ? <Field /> : null}
			{unassigned.length ? (
				<Panel title="Unassigned devices" action={<Link to="/devices">Assign</Link>}>
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Device</TableHead>
								<TableHead>Product</TableHead>
								<TableHead>Serial</TableHead>
								<TableHead>Port</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{unassigned.map((d) => (
								<TableRow key={d.path}>
									<TableCell>{d.path}</TableCell>
									<TableCell>{d.product}</TableCell>
									<TableCell>{d.serial ?? '—'}</TableCell>
									<TableCell>{d.port ?? '—'}</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				</Panel>
			) : null}
		</>
	);
}
