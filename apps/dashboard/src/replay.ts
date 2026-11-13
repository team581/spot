import { useEffect, useRef, useState } from 'react';
import { McapIndexedReader, type IReadable } from '@mcap/core';
import type { FieldView, RobotConfig } from './api';
import { type Detections, decodeDetections, decodeImage } from './live';

/** Values in log time order. Times are nanoseconds, as recorded. */
interface Series<T> {
	times: number[];
	values: T[];
}

/** The index of the last time at or before `time`, or -1. */
function latestAt(times: number[], time: number) {
	let low = 0,
		high = times.length;
	while (low < high) {
		const middle = (low + high) >>> 1;
		if (times[middle]! <= time) low = middle + 1;
		else high = middle;
	}
	return low - 1;
}

export function valueAt<T>(series: Series<T>, time: number) {
	return series.values[Math.max(0, latestAt(series.times, time))];
}

/** Reads byte ranges over HTTP, keeping recent ones since playback rereads the same chunks. */
function httpReadable(url: string, size: bigint): IReadable {
	const cache = new Map<string, Promise<Uint8Array>>();
	return {
		size: async () => size,
		read(offset, length) {
			if (length === 0n) return Promise.resolve(new Uint8Array());
			const key = `${offset}:${length}`;
			let data = cache.get(key);
			if (!data) {
				data = fetch(url, { headers: { Range: `bytes=${offset}-${offset + length - 1n}` } }).then(async (response) => {
					if (response.status !== 206) throw new Error(`Could not read the recording: HTTP ${response.status}`);
					return new Uint8Array(await response.arrayBuffer());
				});
				data.catch(() => cache.delete(key));
			}
			cache.delete(key);
			cache.set(key, data);
			if (cache.size > 48) cache.delete(cache.keys().next().value!);
			return data;
		},
	};
}

export interface Replay {
	/** Nanoseconds, from when the cameras start to the last message. */
	start: number;
	end: number;
	cameras: string[];
	detections: Map<string, Series<Uint8Array>>;
	configs: Series<RobotConfig>;
	fields: Series<FieldView>;
	/** The camera's latest image at or before `time`, within a second. */
	image(camera: string, time: number): Promise<{ time: number; jpeg: Uint8Array } | undefined>;
}

/**
 * Opens a recording without downloading it. Everything but images loads up front; Spot writes
 * those messages before the images, so this reads only the start of the file.
 */
async function openReplay(url: string): Promise<Replay> {
	const head = await fetch(url, { method: 'HEAD' });
	if (!head.ok) throw new Error(`Could not open the recording: HTTP ${head.status}`);
	const reader = await McapIndexedReader.Initialize({
			readable: httpReadable(url, BigInt(head.headers.get('content-length') ?? 0)),
			messageIndexCacheSizeBytes: 8_000_000,
		}),
		topics = [...new Set([...reader.channelsById.values()].map((c) => c.topic))],
		cameras = topics
			.filter((t) => t.endsWith('/detections'))
			.map((t) => t.slice(1, -'/detections'.length))
			.sort(),
		detections = new Map(cameras.map((c) => [c, { times: [], values: [] } as Series<Uint8Array>])),
		configs: Series<RobotConfig> = { times: [], values: [] },
		fields: Series<FieldView> = { times: [], values: [] },
		text = new TextDecoder(),
		wanted = topics.filter((t) => t.endsWith('/detections') || t === '/spot/config' || t === '/spot/field');
	for await (const message of reader.readMessages({ topics: wanted })) {
		const topic = reader.channelsById.get(message.channelId)!.topic,
			time = Number(message.logTime),
			series =
				topic === '/spot/config'
					? configs
					: topic === '/spot/field'
						? fields
						: detections.get(topic.slice(1, -'/detections'.length));
		series?.times.push(time);
		series?.values.push(series === configs || series === fields ? JSON.parse(text.decode(message.data)) : message.data);
	}
	const firsts = [...detections.values()].flatMap((s) => s.times.slice(0, 1));
	return {
		// Cameras start within moments of each other; open once they all have, unless one is late.
		start: firsts.length
			? Math.min(Math.max(...firsts), Math.min(...firsts) + 1e9)
			: Number(reader.statistics?.messageStartTime ?? 0n),
		end: Number(reader.statistics?.messageEndTime ?? 0n),
		cameras,
		detections,
		configs,
		fields,
		async image(camera, time) {
			for await (const message of reader.readMessages({
				topics: [`/${camera}/image`],
				startingAt: BigInt(Math.max(0, Math.round(time - 1e9))),
				endingAt: BigInt(Math.round(time)),
				reverse: true,
			}))
				return { time: Number(message.logTime), jpeg: decodeImage(message.data) ?? new Uint8Array() };
			return undefined;
		},
	};
}

/** The camera's detections at `time`: exactly then, or the latest within half a second. */
export function detectionsAt(replay: Replay, camera: string, time: number, exact = false): Detections | undefined {
	const series = replay.detections.get(camera),
		index = series ? latestAt(series.times, time) : -1;
	if (!series || index < 0) return undefined;
	const at = series.times[index]!;
	if (exact ? at !== time : time - at > 0.5e9) return undefined;
	return decodeDetections(series.values[index]!);
}

export function useReplay(url: string) {
	const [state, setState] = useState<{ url?: string; replay?: Replay; error?: Error }>({});
	useEffect(() => {
		let current = true;
		openReplay(url).then(
			(replay) => current && setState({ url, replay }),
			(error: Error) => current && setState({ url, error }),
		);
		return () => {
			current = false;
		};
	}, [url]);
	return state.url === url ? state : {};
}

interface Frame {
	time: number;
	url: string;
}

/** Each camera's image at `time`. Requests run one batch at a time, skipping to the latest time. */
export function useReplayImages(replay: Replay | undefined, time: number) {
	const [frames, setFrames] = useState<{ images: Map<string, Frame>; error?: Error }>({ images: new Map() }),
		wanted = useRef(time),
		busy = useRef(false),
		urls = useRef<string[]>([]);
	useEffect(
		() => () => {
			for (const url of urls.current) URL.revokeObjectURL(url);
			urls.current = [];
		},
		[replay],
	);
	useEffect(() => {
		wanted.current = time;
		if (!replay || busy.current) return;
		busy.current = true;
		void (async () => {
			let fetched: number | undefined;
			try {
				while (fetched !== wanted.current) {
					const at = (fetched = wanted.current),
						results = await Promise.all(replay.cameras.map((camera) => replay.image(camera, at))),
						images = new Map<string, Frame>(),
						previous = urls.current;
					urls.current = [];
					results.forEach((result, i) => {
						if (!result) return;
						const url = URL.createObjectURL(new Blob([result.jpeg as Uint8Array<ArrayBuffer>], { type: 'image/jpeg' }));
						urls.current.push(url);
						images.set(replay.cameras[i]!, { time: result.time, url });
					});
					setFrames({ images });
					for (const url of previous) URL.revokeObjectURL(url);
				}
			} catch (error) {
				setFrames((frames) => ({ ...frames, error: error as Error }));
			} finally {
				busy.current = false;
			}
		})();
	}, [replay, time]);
	return frames;
}
