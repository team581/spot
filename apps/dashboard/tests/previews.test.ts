import { afterEach, expect, test, vi } from 'vite-plus/test';
import { api } from '../src/api';
import { PreviewStore } from '../src/previews';
import { initialStatus, type Frame, type Status } from '../src/types';
vi.mock('../src/api', () => ({ api: vi.fn() }));
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
	image: 'AA==',
};
const status = (ids: string[]): Status => ({
	...initialStatus,
	revision: 'a',
	cameras: ids.map((identity) => ({ identity, name: identity, connected: true, calibrated: true })),
});
const visible = { getBoundingClientRect: () => ({ top: 0, bottom: 10 }) } as Element;
const offscreen = { getBoundingClientRect: () => ({ top: 2000, bottom: 2100 }) } as Element;
afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.resetAllMocks();
});
function setup() {
	vi.useFakeTimers();
	vi.stubGlobal('document', { hidden: false });
	vi.stubGlobal('innerHeight', 1000);
	vi.mocked(api).mockResolvedValue(frame);
	return new PreviewStore();
}
test('one scheduler requests at most eight visible cameras; hidden pages make no requests', async () => {
	const store = setup(),
		ids = Array.from({ length: 10 }, (_, i) => String(i).repeat(64));
	vi.stubGlobal(
		'createImageBitmap',
		vi.fn(async () => ({ close: vi.fn() })),
	);
	ids.forEach((id) => store.register(id, visible));
	store.register('f'.repeat(64), offscreen);
	store.start(() => status(ids));
	await vi.advanceTimersByTimeAsync(1);
	expect(api).toHaveBeenCalledTimes(8);
	vi.mocked(api).mockClear();
	vi.stubGlobal('document', { hidden: true });
	await vi.advanceTimersByTimeAsync(100);
	expect(api).not.toHaveBeenCalled();
	store.stop();
});
test('an in-flight response cannot replace a paused inspection frame; resume releases the bitmap', async () => {
	const store = setup(),
		id = 'a'.repeat(64),
		snapshot = status([id]),
		bitmap = { close: vi.fn() };
	vi.stubGlobal(
		'createImageBitmap',
		vi.fn(async () => bitmap),
	);
	store.register(id, visible);
	store.start(() => snapshot);
	await vi.advanceTimersByTimeAsync(1);
	let finish!: (frame: Frame) => void;
	vi.mocked(api).mockImplementationOnce(
		() =>
			new Promise<Frame>((resolve) => {
				finish = resolve;
			}),
	);
	await vi.advanceTimersByTimeAsync(50);
	store.toggle(id, snapshot);
	finish({ ...frame, sequence: 2 });
	await vi.advanceTimersByTimeAsync(1);
	expect(store.get(id).paused).toBe(true);
	expect(store.get(id).held?.sequence).toBe(1);
	store.toggle(id, snapshot);
	expect(bitmap.close).toHaveBeenCalled();
	expect(store.get(id).data).toBeUndefined();
	store.stop();
});
test('unmounting the scheduler closes late bitmaps without publishing stale data', async () => {
	const store = setup(),
		id = 'a'.repeat(64),
		bitmap = { close: vi.fn() };
	let finish!: (bitmap: ImageBitmap) => void;
	vi.stubGlobal(
		'createImageBitmap',
		() =>
			new Promise<ImageBitmap>((resolve) => {
				finish = resolve;
			}),
	);
	store.register(id, visible);
	store.start(() => status([id]));
	await vi.advanceTimersByTimeAsync(1);
	store.stop();
	finish(bitmap as unknown as ImageBitmap);
	await vi.advanceTimersByTimeAsync(1);
	expect(bitmap.close).toHaveBeenCalledOnce();
	expect(store.get(id).data).toBeUndefined();
});
