import { useEffect, useMemo, useState } from 'react';
import { FoxgloveClient } from './foxglove';
import { decodeDetections } from './detections';
import type { Detections } from './detections';
import { decodeImage, useCloseReplaced } from './image';

// The dev server proxies the socket so `dev:jetson` reaches Spot's server too.
const foxglove = new FoxgloveClient(
	import.meta.env.DEV ? `ws://${location.host}/foxglove` : `ws://${location.hostname}:5801`,
);

/** The latest message on `topic`, decoded at most once per animation frame. */
function useTopic<T>(topic: string, decode: (payload: Uint8Array) => T) {
	const [value, setValue] = useState<T>();
	useEffect(() => {
		let frame = 0;
		let latest: Uint8Array | undefined;
		const unsubscribe = foxglove.subscribe(topic, (payload) => {
			latest = payload;
			frame ||= requestAnimationFrame(() => {
				frame = 0;
				setValue(decode(latest!));
			});
		});
		return () => {
			unsubscribe();
			cancelAnimationFrame(frame);
			setValue(undefined);
		};
		// oxlint-disable-next-line react/exhaustive-effect-dependencies -- The animation callback captures decode; changing it must replace the subscription.
	}, [topic, decode]);
	return value;
}

const text = new TextDecoder();

export const useDetections = (camera: string) => useTopic(`/${camera}/detections`, decodeDetections);

/** The latest detections from each camera, updated at most once per animation frame. */
export function useAllDetections(cameras: string[]) {
	const [value, setValue] = useState(new Map<string, Detections>());
	const key = cameras.join('\n');
	// react-doctor-disable-next-line react-doctor/effect-needs-cleanup -- The cleanup calls every collected unsubscribe.
	useEffect(() => {
		const latest = new Map<string, Uint8Array>();
		let frame = 0;
		const unsubscribes = key
			.split('\n')
			.filter(Boolean)
			.map((camera) =>
				foxglove.subscribe(`/${camera}/detections`, (payload) => {
					latest.set(camera, payload);
					frame ||= requestAnimationFrame(() => {
						frame = 0;
						setValue(new Map([...latest].map(([name, bytes]) => [name, decodeDetections(bytes)])));
					});
				}),
			);
		return () => {
			for (const unsubscribe of unsubscribes) {
				unsubscribe();
			}
			cancelAnimationFrame(frame);
			setValue(new Map());
		};
	}, [key]);
	return value;
}

/** Each camera's latest image as a bitmap, decoded at most once per animation frame. */
export function useAllImages(cameras: string[]) {
	const [value, setValue] = useState(new Map<string, ImageBitmap>());
	const key = cameras.join('\n');
	// react-doctor-disable-next-line react-doctor/effect-needs-cleanup -- The cleanup calls every collected unsubscribe.
	useEffect(() => {
		const latest = new Map<string, Uint8Array>();
		const bitmaps = new Map<string, ImageBitmap>();
		const run = { decoding: false, frame: 0, stopped: false };
		const decode = async () => {
			run.decoding = true;
			while (latest.size > 0 && !run.stopped) {
				const batch = [...latest];
				latest.clear();
				// oxlint-disable-next-line no-await-in-loop -- Finish each batch before decoding newer images.
				const decoded = await Promise.all(
					batch.map(async ([camera, jpeg]) => {
						try {
							// oxlint-disable-next-line typescript/no-unsafe-type-assertion -- Foxglove image bytes are views into WebSocket ArrayBuffers, never SharedArrayBuffers.
							return [camera, await createImageBitmap(new Blob([jpeg as Uint8Array<ArrayBuffer>]))] as const;
						} catch {
							return undefined;
						}
					}),
				);
				for (const [camera, bitmap] of decoded.filter((d) => d !== undefined)) {
					if (run.stopped) {
						bitmap.close();
						continue;
					}
					bitmaps.set(camera, bitmap);
				}
				if (!run.stopped) {
					setValue(new Map(bitmaps));
				}
			}
			run.decoding = false;
		};
		const unsubscribes = key
			.split('\n')
			.filter(Boolean)
			.map((camera) =>
				foxglove.subscribe(`/${camera}/image`, (payload) => {
					latest.set(camera, decodeImage(payload));
					run.frame ||= requestAnimationFrame(() => {
						run.frame = 0;
						if (!run.decoding) {
							void decode();
						}
					});
				}),
			);
		return () => {
			run.stopped = true;
			for (const unsubscribe of unsubscribes) {
				unsubscribe();
			}
			cancelAnimationFrame(run.frame);
			setValue(new Map());
		};
	}, [key]);
	useCloseReplaced([...value.values()]);
	return value;
}

export interface Charuco {
	width: number;
	height: number;
	ids: number[];
	corners: [number, number][];
}
// oxlint-disable-next-line typescript/no-unsafe-type-assertion -- Spot serializes this topic from the backend ChArUco schema.
const decodeCharuco = (payload: Uint8Array) => JSON.parse(text.decode(payload)) as Charuco;
/** ChArUco board corners, only published while the camera is being calibrated. */
export const useCharuco = (camera: string) => useTopic(`/${camera}/charuco`, decodeCharuco);

/** A blob URL for the camera's latest JPEG. */
export function useImage(camera: string) {
	const jpeg = useTopic(`/${camera}/image`, decodeImage);
	const url = useMemo(
		// oxlint-disable-next-line typescript/no-unsafe-type-assertion -- Foxglove image bytes are views into WebSocket ArrayBuffers, never SharedArrayBuffers.
		() => jpeg && URL.createObjectURL(new Blob([jpeg as Uint8Array<ArrayBuffer>], { type: 'image/jpeg' })),
		[jpeg],
	);
	useEffect(
		() => () => {
			if (url) {
				URL.revokeObjectURL(url);
			}
		},
		[url],
	);
	return url;
}
