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
const maxStreams = 8;
/** One frame message: u32 header length, JSON header, JPEG bytes. */
function parseFrame(message: ArrayBuffer): { frame: Frame; jpeg: Blob } {
	const length = new DataView(message).getUint32(0);
	const frame = JSON.parse(new TextDecoder().decode(new Uint8Array(message, 4, length))) as Frame;
	return { frame, jpeg: new Blob([new Uint8Array(message, 4 + length)], { type: 'image/jpeg' }) };
}
/** Streams previews only for on-screen, unpaused feeds; the service pushes each new frame. */
export class PreviewStore {
	private views = new Map<string, Preview>();
	private elements = new Map<string, Set<Element>>();
	private onScreen = new Set<Element>();
	private listeners = new Map<string, Set<() => void>>();
	private sockets = new Map<string, WebSocket>();
	private observer?: IntersectionObserver;
	private status?: () => Status;
	private retry?: ReturnType<typeof setTimeout>;
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
		this.observer?.observe(element);
		return () => {
			set.delete(element);
			if (!set.size) this.elements.delete(id);
			this.observer?.unobserve(element);
			this.onScreen.delete(element);
			this.reconcile();
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
		this.reconcile();
	}
	markStale(id?: string) {
		for (const [key, view] of this.views)
			if ((id === undefined || key === id) && view.data)
				this.update(key, { ...view, data: { ...view.data, stale: true } });
	}
	prune(ids: string[]) {
		for (const [id, view] of this.views)
			if (!ids.includes(id)) {
				for (const bitmap of new Set([view.bitmap, view.held?.bitmap])) bitmap?.close();
				this.views.delete(id);
			}
		this.reconcile();
	}
	private onVisibility = () => this.reconcile();
	start(status: () => Status) {
		this.status = status;
		this.observer = new IntersectionObserver((entries) => {
			for (const entry of entries)
				entry.isIntersecting ? this.onScreen.add(entry.target) : this.onScreen.delete(entry.target);
			this.reconcile();
		});
		for (const set of this.elements.values()) for (const element of set) this.observer.observe(element);
		document.addEventListener('visibilitychange', this.onVisibility);
	}
	stop() {
		this.status = undefined;
		this.observer?.disconnect();
		this.observer = undefined;
		this.onScreen.clear();
		clearTimeout(this.retry);
		document.removeEventListener('visibilitychange', this.onVisibility);
		this.reconcile();
		this.prune([]);
	}
	/** Open sockets for wanted feeds and close the rest. */
	private reconcile() {
		const cameras = new Set(this.status?.().cameras.map((c) => c.identity));
		const wanted = new Set(
			document.hidden || !this.status
				? []
				: [...this.elements]
						.filter(
							([id, elements]) =>
								cameras.has(id) && !this.get(id).paused && [...elements].some((el) => this.onScreen.has(el)),
						)
						.map(([id]) => id)
						.slice(0, maxStreams),
		);
		for (const [id, socket] of this.sockets)
			if (!wanted.has(id)) {
				this.sockets.delete(id);
				socket.close();
			}
		for (const id of wanted) if (!this.sockets.has(id)) this.open(id);
	}
	private open(id: string) {
		const socket = new WebSocket(
			`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/frames/${id}`,
		);
		socket.binaryType = 'arraybuffer';
		let latest = 0;
		socket.onmessage = async (event: MessageEvent<ArrayBuffer>) => {
			const order = ++latest,
				{ frame, jpeg } = parseFrame(event.data),
				bitmap = await createImageBitmap(jpeg).catch(() => undefined);
			// Drop undecodable frames and decodes that finished after a newer frame, a pause, or a closed stream.
			if (!bitmap || order !== latest || this.sockets.get(id) !== socket || this.get(id).paused) {
				bitmap?.close();
				return;
			}
			this.get(id).bitmap?.close();
			this.update(id, { paused: false, data: frame, bitmap, received: performance.now() });
		};
		socket.onclose = () => {
			if (this.sockets.get(id) !== socket) return;
			this.sockets.delete(id);
			this.markStale(id);
			clearTimeout(this.retry);
			this.retry = setTimeout(() => this.reconcile(), 1000);
		};
		this.sockets.set(id, socket);
	}
}
