import { expect, test } from 'vite-plus/test';
import { parseMessageData } from './foxglove';

test('parseMessageData splits the header from the payload', () => {
	const frame = new Uint8Array([0x01, 7, 0, 0, 0, 0x00, 0x01, 0, 0, 0, 0, 0, 0, 0xaa, 0xbb]);
	const message = parseMessageData(frame.buffer)!;
	expect(message.subscriptionId).toBe(7);
	expect(message.logTime).toBe(256n);
	expect([...message.payload]).toStrictEqual([0xaa, 0xbb]);
	expect(parseMessageData(new Uint8Array([0x02, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]).buffer)).toBeUndefined();
});
