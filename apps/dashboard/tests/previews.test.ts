import { afterEach, beforeEach, expect, test, vi } from 'vite-plus/test';
import { PreviewStore } from '../src/previews';
import { initialStatus, type Frame, type Status } from '../src/types';
const frame: Frame = {
	sequence: 1,
	capture_epoch: 'capture',
	generation: 'a',
	width: 640,
	height: 480,
	age_s: 0.01,
	stale: false,
	processed: true,
	tags: [],
};
const status = (ids: string[]): Status => ({
	...initialStatus,
	revision: 'a',
	cameras: ids.map((identity) => ({ identity, name: identity, connected: true, calibrated: true })),
});
/** Encode a frame message the way the service does. */
function message(value: Frame) {
	const header = new TextEncoder().encode(JSON.stringify(value)),
		bytes = new Uint8Array(4 + header.length + 2);
	new DataView(bytes.buffer).setUint32(0, header.length);
	bytes.set(header, 4);
	return { data: bytes.buffer } as MessageEvent<ArrayBuffer>;
}
class FakeSocket {
	static open: FakeSocket[] = [];
	binaryType = '';
	onmessage?: (event: MessageEvent<ArrayBuffer>) => Promise<void>;
	onclose?: () => void;
	constructor(readonly url: string) {
		FakeSocket.open.push(this);
	}
	close() {
		FakeSocket.open = FakeSocket.open.filter((socket) => socket !== this);
	}
}
let intersect: (entries: { target: Element; isIntersecting: boolean }[]) => void;
beforeEach(() => {
	FakeSocket.open = [];
	vi.stubGlobal('document', { hidden: false, addEventListener: vi.fn(), removeEventListener: vi.fn() });
	vi.stubGlobal('location', { protocol: 'http:', host: 'spot.local:5800' });
	vi.stubGlobal('WebSocket', FakeSocket);
	vi.stubGlobal(
		'IntersectionObserver',
		class {
			constructor(callback: typeof intersect) {
				intersect = callback;
			}
			observe() {}
			unobserve() {}
			disconnect() {}
		},
	);
});
afterEach(() => {
	vi.unstubAllGlobals();
});
function show(store: PreviewStore, id: string, visible = true) {
	const element = {} as Element;
	store.register(id, element);
	intersect([{ target: element, isIntersecting: visible }]);
}
test('streams at most eight on-screen cameras and closes every stream when the page is hidden', () => {
	const store = new PreviewStore(),
		ids = Array.from({ length: 10 }, (_, i) => String(i).repeat(64));
	store.start(() => status([...ids, 'f'.repeat(64)]));
	ids.forEach((id) => show(store, id));
	show(store, 'f'.repeat(64), false);
	expect(FakeSocket.open.map((s) => s.url)).toEqual(
		ids.slice(0, 8).map((id) => `ws://spot.local:5800/api/frames/${id}`),
	);
	vi.stubGlobal('document', { hidden: true, removeEventListener: vi.fn() });
	store.prune([...ids]);
	expect(FakeSocket.open).toEqual([]);
	store.stop();
});
test('pausing closes the stream; a frame decoded after the pause cannot replace the held frame', async () => {
	const store = new PreviewStore(),
		id = 'a'.repeat(64),
		snapshot = status([id]),
		bitmaps = [{ close: vi.fn() }, { close: vi.fn() }];
	let finish!: (bitmap: unknown) => void;
	vi.stubGlobal(
		'createImageBitmap',
		vi
			.fn()
			.mockResolvedValueOnce(bitmaps[0])
			.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve))),
	);
	store.start(() => snapshot);
	show(store, id);
	const [socket] = FakeSocket.open;
	await socket.onmessage!(message(frame));
	expect(store.get(id).data?.sequence).toBe(1);
	const late = socket.onmessage!(message({ ...frame, sequence: 2 }));
	store.toggle(id, snapshot);
	expect(FakeSocket.open).toEqual([]);
	finish(bitmaps[1]);
	await late;
	expect(store.get(id).held?.sequence).toBe(1);
	expect(bitmaps[1].close).toHaveBeenCalled();
	store.toggle(id, snapshot);
	expect(bitmaps[0].close).toHaveBeenCalled();
	expect(FakeSocket.open).toHaveLength(1);
	store.stop();
});
