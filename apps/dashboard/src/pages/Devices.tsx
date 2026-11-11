import { useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import type { CameraConfig, DeviceStatus } from '../api';
import type { Json } from '../overrides';
import { useConfig, useDevices, useEditOverrides } from '../queries';
import { ErrorText, PageTitle, Panel } from '../components/common';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

const defaultMode = '1280x800@120';

function Assign({
	device: d,
	cameras,
	shared,
	edit,
}: {
	device: DeviceStatus;
	cameras: Record<string, CameraConfig>;
	shared: boolean;
	edit: ReturnType<typeof useEditOverrides>;
}) {
	const [name, setName] = useState(d.camera ?? ''),
		[by, setBy] = useState<'serial' | 'port'>(d.serial && !shared ? 'serial' : d.port ? 'port' : 'serial'),
		camera = name.trim();
	const assign = () => {
		const other = by === 'serial' ? 'port' : 'serial',
			changes: [string[], Json][] = [[['cameras', camera, by], d[by]!]];
		// A camera is selected by exactly one of serial or port.
		if (cameras[camera]?.[other] != null) changes.push([['cameras', camera, other], null]);
		// New cameras default to a mode this device may not support.
		if (!cameras[camera] && !d.modes.includes(defaultMode) && d.modes[0])
			changes.push([['cameras', camera, 'mode'], d.modes[0]]);
		edit.set(changes);
	};
	return (
		<form
			className="flex flex-wrap gap-2"
			onSubmit={(e) => {
				e.preventDefault();
				assign();
			}}
		>
			<Input
				className="w-40"
				placeholder="Camera name"
				list="camera-names"
				value={name}
				onChange={(e) => setName(e.target.value)}
			/>
			<NativeSelect value={by} onChange={(e) => setBy(e.target.value as 'serial' | 'port')}>
				<NativeSelectOption value="serial" disabled={!d.serial}>
					By serial
				</NativeSelectOption>
				<NativeSelectOption value="port" disabled={!d.port}>
					By port
				</NativeSelectOption>
			</NativeSelect>
			<Button type="submit" variant="outline" disabled={!camera || !d[by] || edit.isPending}>
				Assign
			</Button>
		</form>
	);
}

export default function Devices() {
	const devices = useDevices().data ?? [],
		cameras = useConfig().data?.config?.cameras ?? {},
		edit = useEditOverrides(),
		serials = devices.map((d) => d.serial).filter(Boolean),
		shared = new Set(serials.filter((s, i) => serials.indexOf(s) !== i));
	return (
		<>
			<PageTitle>Devices</PageTitle>
			<p className="max-w-3xl text-sm text-muted-foreground">
				Assign each connected camera to a camera name from the robot config, or a new one. Select cameras by serial when
				it is unique, otherwise by USB port. Assignments are saved as overrides until the robot config matches.
			</p>
			{shared.size ? (
				<Alert>
					<TriangleAlert className="text-warning!" />
					<AlertDescription>
						Serial {[...shared].join(', ')} is shared by several devices. Select those cameras by port, or reflash them
						with unique serials.
					</AlertDescription>
				</Alert>
			) : null}
			<Panel>
				{devices.length ? (
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Device</TableHead>
								<TableHead>Product</TableHead>
								<TableHead>Serial</TableHead>
								<TableHead>Port</TableHead>
								<TableHead>Camera</TableHead>
								<TableHead>Assign</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{devices.map((d) => (
								<TableRow key={d.path}>
									<TableCell>{d.path}</TableCell>
									<TableCell>{d.product}</TableCell>
									<TableCell className={d.serial && shared.has(d.serial) ? 'text-warning' : undefined}>
										{d.serial ?? '—'}
									</TableCell>
									<TableCell>{d.port ?? '—'}</TableCell>
									<TableCell>{d.camera ?? <span className="text-muted-foreground">Unassigned</span>}</TableCell>
									<TableCell>
										<Assign
											device={d}
											cameras={cameras}
											shared={Boolean(d.serial && shared.has(d.serial))}
											edit={edit}
										/>
									</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				) : (
					<p className="text-sm">No cameras connected.</p>
				)}
				<ErrorText error={edit.error} />
			</Panel>
			<datalist id="camera-names">
				{Object.keys(cameras).map((n) => (
					<option key={n} value={n} />
				))}
			</datalist>
		</>
	);
}
