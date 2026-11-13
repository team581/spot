/** A minimal Foxglove WebSocket client: subscribes to topics by name and delivers raw message payloads. */

interface Channel {
	id: number;
	topic: string;
}
type ServerMessage = { op: 'advertise'; channels: Channel[] } | { op: 'unadvertise'; channelIds: number[] };
type Listener = (payload: Uint8Array) => void;

/** Splits a binary server frame, returning undefined for anything but message data. */
export function parseMessageData(data: ArrayBuffer) {
	const view = new DataView(data);
	if (data.byteLength < 13 || view.getUint8(0) !== 0x01) {
		return undefined;
	}
	return {
		logTime: view.getBigUint64(5, true),
		payload: new Uint8Array(data, 13),
		subscriptionId: view.getUint32(1, true),
	};
}

/** Returns the first length-delimited protobuf field numbered `field`. */
export function protobufBytes(message: Uint8Array, field: number) {
	let i = 0;
	const varint = () => {
		let byte;
		let scale = 1;
		let value = 0;
		do {
			byte = message[i++] ?? 0;
			value += (byte & 0x7f) * scale;
			scale *= 128;
		} while (byte & 0x80);
		return value;
	};
	while (i < message.length) {
		const key = varint();
		const wire = key % 8;
		if (wire === 0) {
			varint();
		} else if (wire === 1) {
			i += 8;
		} else if (wire === 5) {
			i += 4;
		} else if (wire === 2) {
			const length = varint();
			if (Math.floor(key / 8) === field) {
				return message.subarray(i, i + length);
			}
			i += length;
		} else {
			return undefined;
		}
	}
	return undefined;
}

export class FoxgloveClient {
	readonly #url: string;
	#ws: WebSocket | undefined;
	#retry: ReturnType<typeof setTimeout> | undefined;
	#nextId = 1;
	readonly #listeners = new Map<string, Set<Listener>>();
	/** Advertised channel IDs by topic. */
	readonly #channels = new Map<string, number>();
	/** Active subscription IDs by topic, and topics by subscription ID. */
	readonly #subscriptions = new Map<string, number>();
	readonly #topics = new Map<number, string>();

	constructor(url: string) {
		this.#url = url;
	}

	subscribe(topic: string, listener: Listener) {
		let listeners = this.#listeners.get(topic);
		if (!listeners) {
			this.#listeners.set(topic, (listeners = new Set()));
		}
		listeners.add(listener);
		this.#connect();
		this.#sync(topic);
		return () => {
			listeners.delete(listener);
			if (listeners.size > 0) {
				return;
			}
			this.#listeners.delete(topic);
			this.#sync(topic);
		};
	}

	#connect() {
		if (this.#ws || this.#retry) {
			return;
		}
		const ws = new WebSocket(this.#url, ['foxglove.sdk.v1']);
		ws.binaryType = 'arraybuffer';
		ws.addEventListener('message', ({ data }) => {
			if (typeof data === 'string') {
				this.#control(JSON.parse(data));
			} else {
				this.#data(data);
			}
		});
		ws.addEventListener('close', () => {
			this.#ws = undefined;
			this.#channels.clear();
			this.#subscriptions.clear();
			this.#topics.clear();
			if (this.#listeners.size > 0) {
				this.#retry = setTimeout(() => {
					this.#retry = undefined;
					this.#connect();
				}, 1000);
			}
		});
		this.#ws = ws;
	}

	#control(message: ServerMessage) {
		if (message.op === 'advertise') {
			for (const channel of message.channels) {
				this.#channels.set(channel.topic, channel.id);
				this.#sync(channel.topic);
			}
		} else if (message.op === 'unadvertise') {
			for (const [topic, id] of this.#channels) {
				if (message.channelIds.includes(id)) {
					this.#channels.delete(topic);
					this.#topics.delete(this.#subscriptions.get(topic)!);
					this.#subscriptions.delete(topic);
				}
			}
		}
	}

	#data(data: ArrayBuffer) {
		const message = parseMessageData(data);
		const topic = message && this.#topics.get(message.subscriptionId);
		if (topic) {
			for (const listener of this.#listeners.get(topic) ?? []) {
				listener(message.payload);
			}
		}
	}

	/** Subscribes to or unsubscribes from `topic` to match its listeners. */
	#sync(topic: string) {
		const ws = this.#ws;
		const channelId = this.#channels.get(topic);
		const id = this.#subscriptions.get(topic);
		if (ws?.readyState !== WebSocket.OPEN) {
			return;
		}
		if (this.#listeners.has(topic) && channelId !== undefined && id === undefined) {
			const subscriptionId = this.#nextId++;
			this.#subscriptions.set(topic, subscriptionId);
			this.#topics.set(subscriptionId, topic);
			ws.send(JSON.stringify({ op: 'subscribe', subscriptions: [{ channelId, id: subscriptionId }] }));
		} else if (!this.#listeners.has(topic) && id !== undefined) {
			this.#subscriptions.delete(topic);
			this.#topics.delete(id);
			ws.send(JSON.stringify({ op: 'unsubscribe', subscriptionIds: [id] }));
		}
	}
}
