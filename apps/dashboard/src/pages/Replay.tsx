import { useEffect, useState } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { Download, Pause, Play } from 'lucide-react';
import { detectionsAt, type Replay, useReplay, useReplayImages, valueAt } from '../replay';
import { ErrorText, PageTitle, Panel } from '../components/common';
import { CameraImage } from '../components/LiveView';
import { Field3D } from '../components/Field3D';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Slider } from '@/components/ui/slider';

const SPEEDS = [0.1, 0.25, 0.5, 1, 2];

function Player({ replay }: { replay: Replay }) {
	const [time, setTime] = useState(replay.start),
		[play, setPlay] = useState(false),
		playing = play && time < replay.end,
		[speed, setSpeed] = useState(1),
		{ images, error } = useReplayImages(replay, time),
		config = valueAt(replay.configs, time),
		seconds = (t: number) => ((t - replay.start) / 1e9).toFixed(2);

	useEffect(() => {
		if (!playing) return;
		const clock = { frame: 0, last: performance.now() },
			step = (now: number) => {
				const elapsed = (now - clock.last) * 1e6 * speed;
				clock.last = now;
				setTime((t) => Math.min(replay.end, t + elapsed));
				clock.frame = requestAnimationFrame(step);
			};
		clock.frame = requestAnimationFrame(step);
		return () => cancelAnimationFrame(clock.frame);
	}, [playing, speed, replay]);

	const toggle = () => {
		if (!playing && time >= replay.end) setTime(replay.start);
		setPlay(!playing);
	};
	useEffect(() => {
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== ' ' || (event.target as HTMLElement).closest('input, select, textarea, button')) return;
			event.preventDefault();
			toggle();
		};
		addEventListener('keydown', onKey);
		return () => removeEventListener('keydown', onKey);
	});

	return (
		<>
			<Panel>
				<div className="flex flex-wrap items-center gap-3">
					<Button size="sm" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
						{playing ? <Pause /> : <Play />}
					</Button>
					<span className="w-28 text-sm tabular-nums">
						{seconds(time)} / {seconds(replay.end)} s
					</span>
					<Slider
						className="min-w-48 flex-1"
						min={0}
						max={(replay.end - replay.start) / 1e9}
						step={0.01}
						value={(time - replay.start) / 1e9}
						onValueChange={(v) => setTime(replay.start + (v as number) * 1e9)}
					/>
					<NativeSelect size="sm" aria-label="Speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
						{SPEEDS.map((s) => (
							<NativeSelectOption key={s} value={s}>
								{s}×
							</NativeSelectOption>
						))}
					</NativeSelect>
				</div>
				<ErrorText error={error} />
			</Panel>
			<Panel title="Field">
				<Field3D
					field={replay.fields.values.length ? valueAt(replay.fields, time) : null}
					cameras={replay.cameras.map((name) => ({
						name,
						config: config?.cameras?.[name] ?? { serial: '' },
						detections: detectionsAt(replay, name, time),
					}))}
				/>
			</Panel>
			<div className="grid gap-6 md:grid-cols-2">
				{replay.cameras.map((name) => {
					const frame = images.get(name);
					return (
						<Card key={name} className="gap-0 py-0">
							<header className="px-4 py-3">
								<strong className="font-heading text-base">{name}</strong>
							</header>
							<CameraImage
								image={frame?.url}
								detections={frame ? detectionsAt(replay, name, frame.time, true) : undefined}
								className="rounded-none"
							/>
						</Card>
					);
				})}
			</div>
		</>
	);
}

export default function ReplayPage() {
	const { name } = useParams({ from: '/downloads_/$name' }),
		url = '/recordings/' + encodeURIComponent(name),
		{ replay, error } = useReplay(url);
	return (
		<>
			<PageTitle
				action={
					<Button variant="outline" render={<a href={url} download />}>
						<Download />
						Download
					</Button>
				}
			>
				{name}
			</PageTitle>
			<p className="text-sm">
				<Link to="/downloads">All recordings</Link>
			</p>
			<ErrorText error={error} />
			{replay ? (
				replay.cameras.length ? (
					<Player key={name} replay={replay} />
				) : (
					<p className="text-sm text-muted-foreground">This recording has no camera data.</p>
				)
			) : error ? null : (
				<p className="text-sm text-muted-foreground">Loading recording…</p>
			)}
		</>
	);
}
