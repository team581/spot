import { useEffect, useMemo, useState } from 'react';
import { FoxgloveClient, protobufBytes } from './foxglove';

// The dev server proxies the socket so `dev:jetson` reaches Spot's server too.
const foxglove = new FoxgloveClient(
	import.meta.env.DEV ? `ws://${location.host}/foxglove` : `ws://${location.hostname}:5801`,
);

/** The latest message on `topic`, decoded at most once per animation frame. */
function useTopic<T>(topic: string, decode: (payload: Uint8Array) => T) {
	const [value, setValue] = useState<T>();
	useEffect(() => {
		let latest: Uint8Array | undefined,
			frame = 0;
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
	}, [topic, decode]);
	return value;
}

interface Tag {
	id: number;
	/** Image pixels: bottom-left, bottom-right, top-right, top-left. */
	corners: [number, number][];
	hamming: number;
	decision_margin: number;
	/** Whether the tag contributed to the pose estimate. */
	used: boolean;
}
export interface Candidate {
	x: number;
	y: number;
	z: number;
	/** Degrees. */
	roll: number;
	/** Degrees. */
	pitch: number;
	/** Degrees. */
	yaw: number;
	/** Reprojection error in pixels. */
	error: number;
}
export interface Detections {
	width: number;
	height: number;
	tags: Tag[];
	estimate: null | {
		primary: Candidate;
		alternate: Candidate | null;
		average_tag_distance: number;
		tag_area: number;
	};
}

const text = new TextDecoder();
export const decodeDetections = (payload: Uint8Array) => JSON.parse(text.decode(payload)) as Detections;
// `foxglove.CompressedImage` keeps the JPEG in field 2.
export const decodeImage = (payload: Uint8Array) => protobufBytes(payload, 2);

export const useDetections = (camera: string) => useTopic(`/${camera}/detections`, decodeDetections);

/** The latest detections from each camera, updated at most once per animation frame. */
export function useAllDetections(cameras: string[]) {
	const [value, setValue] = useState(new Map<string, Detections>()),
		key = cameras.join('\n');
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
						setValue(new Map([...latest].map(([name, payload]) => [name, decodeDetections(payload)])));
					});
				}),
			);
		return () => {
			for (const unsubscribe of unsubscribes) unsubscribe();
			cancelAnimationFrame(frame);
			setValue(new Map());
		};
	}, [key]);
	return value;
}

export interface Charuco {
	width: number;
	height: number;
	ids: number[];
	corners: [number, number][];
}
const decodeCharuco = (payload: Uint8Array) => JSON.parse(text.decode(payload)) as Charuco;
/** ChArUco board corners, only published while the camera is being calibrated. */
export const useCharuco = (camera: string) => useTopic(`/${camera}/charuco`, decodeCharuco);

/** A blob URL for the camera's latest JPEG. */
export function useImage(camera: string) {
	const jpeg = useTopic(`/${camera}/image`, decodeImage);
	const url = useMemo(
		() => jpeg && URL.createObjectURL(new Blob([jpeg as Uint8Array<ArrayBuffer>], { type: 'image/jpeg' })),
		[jpeg],
	);
	useEffect(
		() => () => {
			if (url) URL.revokeObjectURL(url);
		},
		[url],
	);
	return url;
}
