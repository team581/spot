import { expect, test } from 'vite-plus/test';
import { parseMessageData, protobufBytes } from './foxglove';

test('parseMessageData splits the header from the payload', () => {
	const frame = new Uint8Array([0x01, 7, 0, 0, 0, 0x00, 0x01, 0, 0, 0, 0, 0, 0, 0xaa, 0xbb]);
	const message = parseMessageData(frame.buffer)!;
	expect(message.subscriptionId).toBe(7);
	expect(message.logTime).toBe(256n);
	expect([...message.payload]).toEqual([0xaa, 0xbb]);
	expect(parseMessageData(new Uint8Array([0x02, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]).buffer)).toBeUndefined();
});

test('protobufBytes finds CompressedImage data after other fields', () => {
	const jpeg = Array.from({ length: 200 }, (_, i) => i);
	const message = new Uint8Array([
		// timestamp = { sec: 300 }
		0x0a,
		0x03,
		0x08,
		0xac,
		0x02,
		// frame_id = "f", out of field order
		0x22,
		0x01,
		0x66,
		// data, with a two-byte length varint
		0x12,
		0xc8,
		0x01,
		...jpeg,
		// format = "jpeg"
		0x1a,
		0x04,
		0x6a,
		0x70,
		0x65,
		0x67,
	]);
	expect([...protobufBytes(message, 2)!]).toEqual(jpeg);
	expect(protobufBytes(message, 5)).toBeUndefined();
});
