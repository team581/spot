import { useForm, useSelector } from '@tanstack/react-form';
import { TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import type { CameraConfig, DeviceStatus } from '../api';
import type { Json } from '../overrides';
import { $api, useConfig, useDevices, useEditOverrides } from '../queries';
import { ErrorText, PageTitle, Panel } from '../components/common';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
	AlertDialog,
	AlertDialogAction,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogTitle,
	AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
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
	const form = useForm({
		defaultValues: { name: d.camera ?? '' },
		onSubmit: ({ value }) => {
			assign(value.name.trim());
		},
	});
	const name = useSelector(form.store, (state) => state.values.name).trim();
	const assign = (camera: string) => {
		const changes: [string[], Json][] = [[['cameras', camera, 'serial'], d.serial!]];
		// The port only tells apart cameras that share a serial.
		if (shared) {
			changes.push([['cameras', camera, 'port'], d.port!]);
		} else if (cameras[camera]?.port != null) {
			changes.push([['cameras', camera, 'port'], null]);
		}
		// New cameras default to a mode this device may not support.
		if (!cameras[camera] && !d.modes.includes(defaultMode) && d.modes[0]) {
			changes.push([['cameras', camera, 'mode'], d.modes[0]]);
		}
		edit.set(changes);
	};
	return (
		<form
			className="flex flex-wrap gap-2"
			onSubmit={(e) => {
				e.preventDefault();
				void form.handleSubmit();
			}}
		>
			<form.Field name="name">
				{(field) => (
					<Input
						className="w-40"
						name={field.name}
						aria-label="Camera name"
						placeholder="Camera name"
						list="camera-names"
						value={field.state.value}
						onBlur={field.handleBlur}
						onChange={(e) => {
							field.handleChange(e.target.value);
						}}
					/>
				)}
			</form.Field>
			<Button type="submit" variant="outline" disabled={!name || !d.serial || (shared && !d.port) || edit.isPending}>
				Assign
			</Button>
		</form>
	);
}

const serialPattern = /^[A-Za-z0-9]{1,48}$/;

/** Writes a new serial to a SWYFT camera's flash. It applies once the camera is replugged. */
function SetSerial({ device: d }: { device: DeviceStatus }) {
	const [open, setOpen] = useState(false);
	const [written, setWritten] = useState<string>();
	const write = $api.useMutation('post', '/api/devices/serial', {
		onSuccess: (_, { body }) => {
			setWritten(body.serial);
			setOpen(false);
		},
	});
	const form = useForm({
		defaultValues: { serial: '' },
		onSubmit: ({ value }) => {
			write.mutate({ body: { path: d.path, serial: value.serial } });
		},
	});
	const serial = useSelector(form.store, (state) => state.values.serial);
	return (
		<>
			<AlertDialog
				open={open}
				onOpenChange={(next) => {
					setOpen(next);
					if (next) {
						form.reset();
						write.reset();
					}
				}}
			>
				<AlertDialogTrigger render={<Button variant="link" size="sm" className="ml-2 h-auto p-0 text-accent-text" />}>
					Set serial
				</AlertDialogTrigger>
				<AlertDialogContent>
					<form
						className="grid gap-4"
						onSubmit={(e) => {
							e.preventDefault();
							void form.handleSubmit();
						}}
					>
						<AlertDialogHeader>
							<AlertDialogTitle>Set {d.path} serial</AlertDialogTitle>
							<AlertDialogDescription>Pauses capture. Replug to apply, then reassign.</AlertDialogDescription>
						</AlertDialogHeader>
						<form.Field name="serial">
							{(field) => (
								<Input
									name={field.name}
									aria-label="New serial"
									placeholder="FRONT"
									maxLength={48}
									value={field.state.value}
									onBlur={field.handleBlur}
									onChange={(e) => {
										field.handleChange(e.target.value);
									}}
								/>
							)}
						</form.Field>
						<ErrorText error={serial && !serialPattern.test(serial) ? 'Letters and digits only' : write.error} />
						<AlertDialogFooter>
							<AlertDialogCancel disabled={write.isPending}>Cancel</AlertDialogCancel>
							<AlertDialogAction type="submit" disabled={!serialPattern.test(serial) || write.isPending}>
								{write.isPending ? 'Writing…' : 'Write'}
							</AlertDialogAction>
						</AlertDialogFooter>
					</form>
				</AlertDialogContent>
			</AlertDialog>
			{written && written !== d.serial ? (
				<p className="text-xs text-muted-foreground">Replug to use {written}</p>
			) : null}
		</>
	);
}

export default function Devices() {
	const devices = useDevices().data ?? [];
	const cameras = useConfig().data?.config?.cameras ?? {};
	const edit = useEditOverrides();
	const serials = devices.map((d) => d.serial).filter(Boolean);
	const shared = new Set(serials.filter((s, i) => serials.indexOf(s) !== i));
	return (
		<>
			<PageTitle>Devices</PageTitle>
			<p className="max-w-3xl text-sm text-muted-foreground">
				Assign each connected camera to a camera name from the robot config, or a new one. Cameras are found by serial;
				cameras that share a serial are also told apart by USB port, so keep those in the same ports. Assignments are
				saved as overrides until the robot config matches.
			</p>
			{shared.size > 0 ? (
				<Alert>
					<TriangleAlert className="text-warning!" />
					<AlertDescription>
						Serial {[...shared].join(', ')} is shared by several devices, so those cameras are also matched by USB port.
						Give them unique serials to move them between ports freely.
					</AlertDescription>
				</Alert>
			) : null}
			<Panel>
				{devices.length > 0 ? (
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
									<TableCell>
										<span className={d.serial && shared.has(d.serial) ? 'text-warning' : undefined}>
											{d.serial ?? '—'}
										</span>
										{d.serial_writable ? <SetSerial device={d} /> : null}
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
