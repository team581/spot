import { create, toBinary } from '@bufbuild/protobuf';
import { McapWriter } from '@mcap/core';
import type { IReadable } from '@mcap/core';
import { expect, test } from 'vite-plus/test';
import { CompressedImageSchema } from './gen/foxglove/CompressedImage_pb';
import { detectionsAt, openRecording, valueAt } from './replay';

const S = 1e9;
const IMAGE_BYTES = 100_000;
const json = (value: unknown) => new TextEncoder().encode(JSON.stringify(value));
/** Detections that saw one tag, identified by its ID. */
const detections = (id: number) =>
	json({
		estimate: null,
		height: 800,
		tags: [{ corners: [], decision_margin: 0, hamming: 0, id, used: true }],
		width: 1280,
	});
/** A JPEG-sized image filled with `byte`. */
const image = (byte: number) =>
	toBinary(
		CompressedImageSchema,
		create(CompressedImageSchema, { data: new Uint8Array(IMAGE_BYTES).fill(byte), format: 'jpeg' }),
	);

/**
 * Writes a recording like Spot's: everything but images first, then images, one message per
 * chunk.
 */
async function record(messages: { topic: string; time: number; data: Uint8Array }[]) {
	const parts: Uint8Array[] = [];
	let size = 0n;
	const writer = new McapWriter({
		chunkSize: 0,
		writable: {
			position: () => size,
			write: async (data) => {
				parts.push(new Uint8Array(data));
				size += BigInt(data.length);
			},
		},
	});
	await writer.start({ library: 'test', profile: '' });
	const channels = new Map<string, number>();
	const ordered = messages.toSorted((a, b) => Number(a.topic.endsWith('/image')) - Number(b.topic.endsWith('/image')));
	for (const [sequence, { topic, time, data }] of ordered.entries()) {
		let channelId = channels.get(topic);
		if (channelId === undefined) {
			const channel = { messageEncoding: 'json', metadata: new Map<string, string>(), schemaId: 0, topic };
			// oxlint-disable-next-line no-await-in-loop -- The writer must finish each call before the next.
			channelId = await writer.registerChannel(channel);
			channels.set(topic, channelId);
		}
		const logTime = BigInt(time);
		// oxlint-disable-next-line no-await-in-loop -- The writer must finish each call before the next.
		await writer.addMessage({ channelId, data, logTime, publishTime: logTime, sequence });
	}
	await writer.end();
	const bytes = new Uint8Array(Number(size));
	let offset = 0;
	for (const part of parts) {
		bytes.set(part, offset);
		offset += part.length;
	}
	return bytes;
}

/** Serves `bytes` from memory, counting the bytes read. */
function memory(bytes: Uint8Array) {
	const reads = { bytes: 0 };
	const readable: IReadable<AbortSignal> = {
		read: async (offset, length) => {
			reads.bytes += Number(length);
			return bytes.slice(Number(offset), Number(offset + length));
		},
		size: async () => BigInt(bytes.length),
	};
	return { readable, reads };
}

const camera = (name: string, from: number, to: number) =>
	Array.from({ length: Math.round((to - from) * 10) + 1 }, (_, i) => ({
		data: detections(i),
		time: Math.round((from + i / 10) * S),
		topic: `/${name}/detections`,
	}));

test('opens a recording without reading its images', async () => {
	const config = { cameras: {}, ignored_tags: [4] };
	const bytes = await record([
		{ data: json(config), time: 0.5 * S, topic: '/spot/config' },
		...camera('front', 1, 3),
		...camera('back', 1.3, 3),
		{ data: image(1), time: S, topic: '/front/image' },
		{ data: image(2), time: 2 * S, topic: '/front/image' },
	]);
	const { readable, reads } = memory(bytes);
	const replay = await openRecording(readable);

	expect(replay.cameras).toStrictEqual(['back', 'front']);
	// Playback starts once every camera has, with the config logged before it.
	expect(replay.start).toBe(1.3 * S);
	expect(valueAt(replay.configs, replay.start)).toStrictEqual(config);
	expect(reads.bytes).toBeLessThan(IMAGE_BYTES);
});

test('a camera that starts late does not hold back playback', async () => {
	const bytes = await record([...camera('front', 1, 2), ...camera('back', 5, 6)]);
	const replay = await openRecording(memory(bytes).readable);
	expect(replay.start).toBe(2 * S);
});

test('detections are the latest within half a second, or exactly at a time', async () => {
	const replay = await openRecording(memory(await record(camera('front', 1, 2))).readable);
	const tag = (time: number, exact = false) => detectionsAt(replay, 'front', time, exact)?.tags[0].id;

	expect(tag(1.25 * S)).toBe(2);
	expect(tag(1.25 * S, true)).toBeUndefined();
	expect(tag(1.2 * S, true)).toBe(2);
	expect(tag(2.6 * S)).toBeUndefined();
});

test('images are the latest within a second', async () => {
	const bytes = await record([
		...camera('front', 1, 2),
		{ data: image(1), time: S, topic: '/front/image' },
		{ data: image(2), time: 1.5 * S, topic: '/front/image' },
	]);
	const replay = await openRecording(memory(bytes).readable);

	await expect(replay.image('front', 2.4 * S)).resolves.toStrictEqual({
		jpeg: new Uint8Array(IMAGE_BYTES).fill(2),
		time: 1.5 * S,
	});
	await expect(replay.image('front', 2.6 * S)).resolves.toBeUndefined();
});
