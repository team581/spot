import { useState } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import type { ControlRange } from '../api';
import type { Json } from '../overrides';
import { useConfig, useDevices, useEditOverrides, useStatus } from '../queries';
import { useDetections } from '../live';
import type { Candidate } from '../detections';
import { DataList, ErrorText, PageTitle, Panel, StateBadge } from '../components/common';
import { fmt } from '../format';
import { LiveView } from '../components/LiveView';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Slider } from '@/components/ui/slider';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

/** A device control slider; unset means the camera's default. */
function ControlSlider({
	label,
	range,
	value,
	onChange,
}: {
	label: string;
	range: ControlRange | undefined;
	value: number | null | undefined;
	onChange: (value: number | null, done: () => void) => void;
}) {
	const [draft, setDraft] = useState<number>();
	if (!range) {
		return (
			<div className="flex flex-col gap-2">
				<Label>{label}</Label>
				<span className="text-sm text-muted-foreground">Not supported by this camera</span>
			</div>
		);
	}
	const shown = draft ?? value ?? range.default;
	return (
		<div className="flex flex-col gap-2">
			<div className="flex items-center justify-between gap-2">
				<Label>{label}</Label>
				<span className="text-sm">
					{shown}
					{value == null && draft === undefined ? <span className="text-muted-foreground"> (default)</span> : null}
				</span>
			</div>
			<div className="flex items-center gap-3">
				<Slider
					min={range.min}
					max={range.max}
					step={range.step || 1}
					value={shown}
					onValueChange={(v) => {
						if (typeof v === 'number') {
							setDraft(v);
						}
					}}
					onValueCommitted={(v) => {
						if (typeof v === 'number') {
							onChange(v, () => {
								setDraft(undefined);
							});
						}
					}}
				/>
				<Button
					variant="outline"
					size="sm"
					disabled={value == null}
					onClick={() => {
						onChange(null, () => {});
					}}
				>
					Reset
				</Button>
			</div>
		</div>
	);
}

function Settings({ name }: { name: string }) {
	const edit = useEditOverrides();
	const camera = useConfig().data?.config?.cameras?.[name];
	const device = useDevices().data?.find((d) => d.camera === name);
	const controls = camera?.controls ?? {};
	const mode = camera?.mode ?? '';
	const modes = device?.modes.includes(mode) || !mode ? (device?.modes ?? []) : [mode, ...(device?.modes ?? [])];
	const range = (control: string) => device?.controls.find((c) => c.name === control);
	const set = (key: string[], value: Json, done?: () => void) => {
		edit.set([[['cameras', name, ...key], value]], { onSettled: done });
	};
	return (
		<Panel title="Settings">
			<div className="flex flex-col gap-2">
				<Label htmlFor="mode">Mode</Label>
				<NativeSelect
					id="mode"
					className="w-full"
					value={mode}
					onChange={(e) => {
						set(['mode'], e.target.value);
					}}
				>
					{modes.map((m) => (
						<NativeSelectOption key={m} value={m}>
							{m}
						</NativeSelectOption>
					))}
				</NativeSelect>
			</div>
			<div className="flex flex-col gap-2">
				<Label htmlFor="auto-exposure">Auto exposure</Label>
				<NativeSelect
					id="auto-exposure"
					className="w-full"
					value={controls.auto_exposure ?? ''}
					disabled={!range('auto_exposure')}
					onChange={(e) => {
						set(['controls', 'auto_exposure'], e.target.value || null);
					}}
				>
					<NativeSelectOption value="">Camera default</NativeSelectOption>
					<NativeSelectOption value="manual">Manual</NativeSelectOption>
					<NativeSelectOption value="aperture_priority">Aperture priority</NativeSelectOption>
				</NativeSelect>
			</div>
			<ControlSlider
				label="Exposure"
				range={range('exposure_time_absolute')}
				value={controls.exposure_time_absolute}
				onChange={(v, done) => {
					set(['controls', 'exposure_time_absolute'], v, done);
				}}
			/>
			<ControlSlider
				label="Gain"
				range={range('gain')}
				value={controls.gain}
				onChange={(v, done) => {
					set(['controls', 'gain'], v, done);
				}}
			/>
			<ErrorText error={edit.error} />
		</Panel>
	);
}

const candidate = (c: Candidate | null | undefined) =>
	c
		? `x ${fmt(c.x, 2)} m · y ${fmt(c.y, 2)} m · z ${fmt(c.z, 2)} m · roll ${fmt(c.roll)}° · pitch ${fmt(c.pitch)}° · yaw ${fmt(c.yaw)}° · error ${fmt(c.error, 2)} px`
		: '—';

function Detections({ name }: { name: string }) {
	const detections = useDetections(name);
	const estimate = detections?.estimate;
	return (
		<>
			<Panel title="Estimate">
				<DataList
					values={{
						Primary: candidate(estimate?.primary),
						Alternate: candidate(estimate?.alternate),
						'Average tag distance': estimate ? `${fmt(estimate.average_tag_distance, 2)} m` : '—',
						'Tag area': estimate ? `${fmt(estimate.tag_area * 100, 2)}%` : '—',
					}}
				/>
			</Panel>
			<Panel title="Detections">
				{detections?.tags.length ? (
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>ID</TableHead>
								<TableHead>Used</TableHead>
								<TableHead>Hamming</TableHead>
								<TableHead>Margin</TableHead>
								<TableHead>Corners (px)</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{detections.tags.map((t) => (
								<TableRow key={`${t.id}:${t.corners.join(',')}`}>
									<TableCell>{t.id}</TableCell>
									<TableCell>{t.used ? 'Yes' : 'No'}</TableCell>
									<TableCell>{t.hamming}</TableCell>
									<TableCell>{fmt(t.decision_margin)}</TableCell>
									<TableCell className="font-mono text-xs">
										{t.corners.map(([x, y]) => `(${x.toFixed(0)}, ${y.toFixed(0)})`).join(' ')}
									</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				) : (
					<p className="text-sm text-muted-foreground">{detections ? 'No tags in view' : 'Waiting for detections'}</p>
				)}
			</Panel>
		</>
	);
}

export default function CameraDetail() {
	const { name } = useParams({ from: '/cameras/$name' });
	const status = useStatus();
	const camera = status.data?.cameras.find((c) => c.name === name);
	if (!camera) {
		return (
			<>
				<PageTitle>{name}</PageTitle>
				<p className="text-sm">
					{status.data ? 'This camera is not configured.' : 'Loading…'} <Link to="/">All cameras</Link>
				</p>
			</>
		);
	}
	return (
		<>
			<PageTitle>{name}</PageTitle>
			<div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
				<div className="flex min-w-0 flex-col gap-6">
					<LiveView camera={name} />
					<Detections name={name} />
				</div>
				<div className="flex flex-col gap-6">
					<Panel title="Status">
						<DataList
							values={{
								State: <StateBadge state={camera.state} />,
								...(camera.error ? { Error: <span className="text-warning">{camera.error}</span> } : {}),
								Mode: camera.mode,
								FPS: fmt(camera.fps),
								'Capture FPS': fmt(camera.capture_fps),
								'Dropped frames': camera.dropped_frames,
								Calibrated: camera.calibrated ? 'Yes' : 'No',
								Required: camera.required ? 'Yes' : 'No',
								Device: camera.device ?? '—',
							}}
						/>
					</Panel>
					<Settings name={name} />
				</div>
			</div>
		</>
	);
}
