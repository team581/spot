import type { Camera, Values } from '../types';
import { errorMessage } from '../errors';
type WriteResult = { value: number; revision?: string };
type Send = (values: Values, revision: string) => Promise<{ values: Values; revision: string }>;
export const finiteText = (text: string) =>
	/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text) && Number.isFinite(Number(text));
export class NumberEdit {
	ack!: number;
	text!: string;
	min!: number;
	max!: number;
	revision!: string;
	preview!: (value: number) => void;
	send!: (value: number, revision: string) => Promise<number | WriteResult>;
	focused = false;
	pending = false;
	error = '';
	conflict = false;
	editRevision: string;
	editVersion: number;
	lastCommit: number;
	previewValue = 0;

	constructor(
		value: number,
		{
			min = -Infinity,
			max = Infinity,
			revision = '',
			preview = () => {},
			commit = async (v: number) => v,
		}: {
			min?: number;
			max?: number;
			revision?: string;
			preview?: (value: number) => void;
			commit?: (value: number, revision: string) => Promise<number | WriteResult>;
		} = {},
	) {
		Object.assign(this, {
			ack: value,
			text: String(value),
			min,
			max,
			revision,
			preview,
			send: commit,
			focused: false,
			pending: false,
			error: '',
			conflict: false,
		});
		this.editRevision = revision;
		this.editVersion = 0;
		this.lastCommit = -1;
	}
	focus() {
		this.focused = true;
		this.editRevision = this.revision;
	}
	input(text: string) {
		this.text = text;
		this.editVersion++;
		this.error = '';
		if (finiteText(text)) this.preview(Number(text));
	}
	readback(value: number, revision: string) {
		if (revision !== this.revision && (this.focused || this.pending) && !this.pending) {
			this.conflict = true;
			this.error = 'Configuration changed; reconcile current values before committing';
		}
		this.ack = value;
		this.revision = revision;
		if (!this.focused && !this.pending && !this.conflict) this.text = String(value);
	}
	reconcile() {
		this.editRevision = this.revision;
		this.conflict = false;
		this.error = '';
		this.lastCommit = -1;
	}
	cancel() {
		this.text = String(this.ack);
		this.error = '';
		this.conflict = false;
		this.lastCommit = this.editVersion;
		this.preview(this.ack);
	}
	async commit() {
		if (this.pending || this.lastCommit === this.editVersion) return false;
		if (this.conflict) {
			this.error = 'Configuration changed; reconcile current values before committing';
			return false;
		}
		if (!finiteText(this.text) || Number(this.text) < this.min || Number(this.text) > this.max) {
			this.error = 'Enter a finite value within the supported limits';
			return false;
		}
		this.lastCommit = this.editVersion;
		this.pending = true;
		const version = this.editVersion;
		try {
			const result = await this.send(Number(this.text), this.editRevision);
			this.ack = typeof result === 'number' ? result : result.value;
			this.revision = typeof result === 'number' ? this.revision : (result.revision ?? this.revision);
			this.editRevision = this.revision;
			if (!this.focused && this.editVersion === version) this.text = String(this.ack);
			return true;
		} catch (error) {
			this.error = errorMessage(error);
			return false;
		} finally {
			this.pending = false;
		}
	}
	step(direction: number, { shiftKey = false, altKey = false } = {}, angle = false) {
		if (!finiteText(this.text)) return false;
		const amount = angle ? (altKey ? 0.1 : shiftKey ? 10 : 1) : altKey ? 0.001 : shiftKey ? 0.1 : 0.01;
		this.input(String(Number((Number(this.text) + direction * amount).toFixed(6))));
		return true;
	}
}
export class LiveTuner {
	values: Values;
	requested: Values;
	revision: string;
	send: Send;
	onChange: () => void;
	conflict: boolean;
	pending: Values | null;
	inFlight: boolean;
	gesture: Values | null;
	finished: boolean;
	error: string;
	timer: ReturnType<typeof setTimeout> | undefined;
	lastSend: number;

	constructor(values: Values, revision: string, send: Send, onChange = () => {}) {
		this.values = { ...values };
		this.requested = { ...values };
		this.revision = revision;
		this.send = send;
		this.onChange = onChange;
		this.conflict = false;
		this.pending = null;
		this.inFlight = false;
		this.gesture = null;
		this.finished = false;
		this.error = '';
		this.timer = undefined;
		this.lastSend = 0;
	}
	begin() {
		if (!this.gesture) {
			this.gesture = { ...this.values };
			this.finished = false;
		}
	}
	request(name: string, value: number, final = false) {
		this.begin();
		this.requested[name] = value;
		this.pending = { ...this.pending, [name]: value };
		if (final) this.finished = true;
		this._schedule();
		this.onChange();
	}
	end() {
		this.finished = true;
		this._schedule();
		this._finish();
	}
	_schedule() {
		if (this.inFlight || !this.pending) return;
		clearTimeout(this.timer);
		this.timer = setTimeout(() => this._flush(), Math.max(0, 250 - (Date.now() - this.lastSend)));
	}
	async _flush() {
		if (this.inFlight || !this.pending) return;
		const values = this.pending;
		this.pending = null;
		this.inFlight = true;
		this.lastSend = Date.now();
		this.onChange();
		try {
			const result = await this.send(values, this.revision);
			this.values = { ...this.values, ...result.values };
			this.revision = result.revision;
			this.error = '';
		} catch (error) {
			this.error = errorMessage(error);
			this.pending = null;
			this.finished = true;
			if (/conflict/i.test(this.error)) this.conflict = true;
		} finally {
			this.inFlight = false;
			this._finish();
			this._schedule();
			this.onChange();
		}
	}
	_finish() {
		if (this.finished && !this.inFlight && !this.pending && this.gesture) {
			this.gesture = null;
			this.finished = false;
		}
	}
	observe(values: Values, revision: string) {
		if (this.inFlight) return;
		if (revision !== this.revision) {
			this.revision = revision;
			this.values = { ...values };
			if (this.gesture) {
				this.pending = null;
				this.finished = true;
				this.error = 'Configuration changed on Spot; edit discarded';
			} else this.requested = { ...values };
		} else this.values = { ...values };
	}
	reconcile(values: Values, revision: string) {
		clearTimeout(this.timer);
		this.pending = null;
		this.gesture = null;
		this.values = { ...values };
		this.requested = { ...values };
		this.revision = revision;
		this.conflict = false;
		this.error = '';
		this.onChange();
	}
	async reset(send: () => Promise<{ values: Values; revision: string }>) {
		this.inFlight = true;
		this.onChange();
		try {
			const result = await send();
			this.revision = result.revision;
			this.values = { ...result.values };
			this.requested = { ...result.values };
		} catch (error) {
			this.error = errorMessage(error);
		} finally {
			this.inFlight = false;
			this.onChange();
		}
	}
	reject(error: unknown) {
		this.error = errorMessage(error);
		this.onChange();
	}

	dispose() {
		clearTimeout(this.timer);
		if (this.pending) this.finished = true;
		void this._flush();
	}
}
export function availableCameraNames(
	names: string[],
	cameras: Pick<Camera, 'logical_name' | 'identity'>[],
	identity: string,
) {
	return names.filter(
		(name) =>
			!cameras.some(
				(camera) =>
					camera.logical_name === name && camera.identity !== identity && !camera.identity.startsWith('missing:'),
			),
	);
}
