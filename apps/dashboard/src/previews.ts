import { api } from './api';
import type { Frame, Geometry, Status } from './types';
export interface Preview {
	paused: boolean;
	data?: Frame;
	bitmap?: ImageBitmap;
	received?: number;
	held?: Frame & {
		bitmap?: ImageBitmap;
		geometry?: Geometry;
		field?: Status['field'];
		heldAt: number;
	};
}
const empty: Preview = { paused: false };
/** Shared scheduler keeps preview traffic bounded to eight visible feeds at 20 Hz. */
export class PreviewStore {
	private views = new Map<string, Preview>();
	private elements = new Map<string, Set<Element>>();
	private listeners = new Map<string, Set<() => void>>();
	private timer: ReturnType<typeof setTimeout> | undefined;
	private running = false;
	private epoch = 0;
	get = (id: string) => this.views.get(id) ?? empty;
	subscribe = (id: string, listener: () => void) => {
		const set = this.listeners.get(id) ?? new Set();
		set.add(listener);
		this.listeners.set(id, set);
		return () => {
			set.delete(listener);
			if (!set.size) this.listeners.delete(id);
		};
	};
	register(id: string, element: Element) {
		const set = this.elements.get(id) ?? new Set();
		set.add(element);
		this.elements.set(id, set);
		return () => {
			set.delete(element);
			if (!set.size) this.elements.delete(id);
		};
	}
	private update(id: string, view: Preview) {
		this.views.set(id, view);
		for (const fn of this.listeners.get(id) ?? []) fn();
	}
	toggle(id: string, status: Status) {
		const view = this.get(id);
		if (!view.data) return;
		if (view.paused) {
			view.bitmap?.close();
			this.update(id, { paused: false });
		} else
			this.update(id, {
				...view,
				paused: true,
				held: {
					...view.data,
					bitmap: view.bitmap,
					geometry: status.cameras.find((c) => c.identity === id)?.geometry,
					field: status.field,
					heldAt: performance.now(),
				},
			});
	}
	markStale() {
		for (const [id, view] of this.views)
			if (view.data) this.update(id, { ...view, data: { ...view.data, stale: true } });
	}
	prune(ids: string[]) {
		for (const [id, view] of this.views)
			if (!ids.includes(id)) {
				for (const bitmap of new Set([view.bitmap, view.held?.bitmap])) bitmap?.close();
				this.views.delete(id);
			}
	}
	start(status: () => Status) {
		if (this.running) return;
		this.running = true;
		const epoch = ++this.epoch;
		const poll = async () => {
			const started = performance.now();
			if (!document.hidden) {
				const visible = [...this.elements]
					.filter(([, elements]) =>
						[...elements].some((el) => {
							const r = el.getBoundingClientRect();
							return r.bottom > 0 && r.top < innerHeight;
						}),
					)
					.slice(0, 8);
				await Promise.allSettled(
					visible.map(async ([id]) => {
						const before = this.get(id);
						if (before.paused || !/^[a-f0-9]{64}$/.test(id)) return;
						try {
							const data = await api<Frame>('/api/frames/' + id);
							let bitmap = before.bitmap;
							if (
								data.image &&
								(!bitmap ||
									data.capture_epoch !== before.data?.capture_epoch ||
									data.sequence !== before.data?.sequence)
							) {
								const bytes = Uint8Array.from(atob(data.image), (c) => c.charCodeAt(0));
								bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/jpeg' }));
							}
							if (epoch !== this.epoch || this.get(id).paused || !status().cameras.some((c) => c.identity === id)) {
								if (bitmap !== before.bitmap) bitmap?.close();
								return;
							}
							if (bitmap !== before.bitmap) before.bitmap?.close();
							this.update(id, { paused: false, data, bitmap, received: performance.now() });
						} catch {
							const current = this.get(id);
							if (current.data) this.update(id, { ...current, data: { ...current.data, stale: true } });
						}
					}),
				);
			}
			if (this.running && epoch === this.epoch)
				this.timer = setTimeout(poll, Math.max(0, 50 - (performance.now() - started)));
		};
		void poll();
	}
	stop() {
		this.running = false;
		this.epoch++;
		clearTimeout(this.timer);
		this.prune([]);
	}
}
