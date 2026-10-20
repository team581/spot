/* Shared state machines; DOM inputs retain their native editing/caret behavior. */
(function (root) {
  "use strict";
  const finiteText = (text) =>
    /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text) &&
    Number.isFinite(Number(text));
  class NumberEdit {
    constructor(
      value,
      {
        min = -Infinity,
        max = Infinity,
        revision = "",
        preview = () => {},
        commit = async (v) => v,
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
        error: "",
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
    input(text) {
      this.text = text;
      this.editVersion++;
      this.error = "";
      if (finiteText(text)) this.preview(Number(text));
    }
    readback(value, revision) {
      if (
        revision !== this.revision &&
        (this.focused || this.pending) &&
        !this.pending
      ) {
        this.conflict = true;
        this.error =
          "Configuration changed; reconcile current values before committing";
      }
      this.ack = value;
      this.revision = revision;
      if (!this.focused && !this.pending && !this.conflict)
        this.text = String(value);
    }
    reconcile() {
      this.editRevision = this.revision;
      this.conflict = false;
      this.error = "";
      this.lastCommit = -1;
    }
    cancel() {
      this.text = String(this.ack);
      this.error = "";
      this.conflict = false;
      this.lastCommit = this.editVersion;
      this.preview(this.ack);
    }
    async commit() {
      if (this.pending || this.lastCommit === this.editVersion) return false;
      if (this.conflict) {
        this.error =
          "Configuration changed; reconcile current values before committing";
        return false;
      }
      if (
        !finiteText(this.text) ||
        Number(this.text) < this.min ||
        Number(this.text) > this.max
      ) {
        this.error = "Enter a finite value within the supported limits";
        return false;
      }
      this.lastCommit = this.editVersion;
      this.pending = true;
      const version = this.editVersion;
      try {
        const result = await this.send(Number(this.text), this.editRevision);
        this.ack = result.value ?? result;
        this.revision = result.revision ?? this.revision;
        this.editRevision = this.revision;
        if (!this.focused && this.editVersion === version)
          this.text = String(this.ack);
        return true;
      } catch (error) {
        this.error = error.message;
        return false;
      } finally {
        this.pending = false;
      }
    }
    step(direction, { shiftKey = false, altKey = false } = {}, angle = false) {
      if (!finiteText(this.text)) return false;
      const amount = angle
        ? altKey
          ? 0.1
          : shiftKey
            ? 10
            : 1
        : altKey
          ? 0.001
          : shiftKey
            ? 0.1
            : 0.01;
      this.input(
        String(Number((Number(this.text) + direction * amount).toFixed(6))),
      );
      return true;
    }
  }
  class History {
    constructor() {
      this.undoStack = [];
      this.redoStack = [];
      this.revision = "";
      this.pending = false;
      this.conflict = false;
    }
    record(before, after, revision) {
      this.revision = revision;
      if (JSON.stringify(before) !== JSON.stringify(after)) {
        this.undoStack.push({ before: { ...before }, after: { ...after } });
        if (this.undoStack.length > 64) this.undoStack.shift();
        this.redoStack = [];
      }
    }
    observe(revision) {
      if (this.revision && this.revision !== revision && !this.pending) {
        this.clear(revision);
        this.conflict = true;
      } else if (!this.revision) this.revision = revision;
    }
    clear(revision) {
      this.undoStack = [];
      this.redoStack = [];
      this.revision = revision;
    }
    async apply(direction, send) {
      const source = direction === "undo" ? this.undoStack : this.redoStack,
        target = direction === "undo" ? this.redoStack : this.undoStack;
      if (!source.length || this.pending || this.conflict) return false;
      const entry = source.at(-1);
      this.pending = true;
      try {
        const result = await send(
          direction === "undo" ? entry.before : entry.after,
          this.revision,
        );
        source.pop();
        target.push(entry);
        this.revision = result.revision;
        return true;
      } finally {
        this.pending = false;
      }
    }
  }
  class LiveTuner {
    constructor(values, revision, send, onChange = () => {}) {
      this.values = { ...values };
      this.requested = { ...values };
      this.revision = revision;
      this.send = send;
      this.onChange = onChange;
      this.history = new History();
      this.history.revision = revision;
      this.pending = null;
      this.inFlight = false;
      this.gesture = null;
      this.finished = false;
      this.error = "";
      this.timer = null;
      this.lastSend = 0;
    }
    begin() {
      if (!this.gesture) {
        this.gesture = { ...this.values };
        this.finished = false;
      }
    }
    request(name, value, final = false) {
      this.begin();
      this.requested[name] = value;
      this.pending = { ...(this.pending || {}), [name]: value };
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
      this.timer = setTimeout(
        () => this._flush(),
        Math.max(0, 250 - (Date.now() - this.lastSend)),
      );
    }
    async _flush() {
      if (this.inFlight || !this.pending) return;
      const values = this.pending;
      this.pending = null;
      this.inFlight = true;
      this.history.pending = true;
      this.lastSend = Date.now();
      this.onChange();
      try {
        const result = await this.send(values, this.revision);
        this.values = { ...this.values, ...result.values };
        this.revision = result.revision;
        this.history.revision = result.revision;
        this.error = "";
      } catch (error) {
        this.error = error.message;
        this.pending = null;
        this.finished = true;
        if (/conflict/i.test(this.error)) {
          this.history.clear(this.revision);
          this.history.conflict = true;
        }
      } finally {
        this.inFlight = false;
        this.history.pending = false;
        this._finish();
        this._schedule();
        this.onChange();
      }
    }
    _finish() {
      if (this.finished && !this.inFlight && !this.pending && this.gesture) {
        if (!this.history.conflict)
          this.history.record(this.gesture, this.values, this.revision);
        this.gesture = null;
        this.finished = false;
      }
    }
    observe(values, revision) {
      if (this.inFlight) return;
      if (revision !== this.revision) {
        this.history.observe(revision);
        this.revision = revision;
        this.values = { ...values };
        if (this.gesture) {
          this.pending = null;
          this.finished = true;
          this.error = "Configuration changed; reconcile before another edit";
        } else this.requested = { ...values };
      } else this.values = { ...values };
    }
    reconcile(values, revision) {
      clearTimeout(this.timer);
      this.pending = null;
      this.gesture = null;
      this.values = { ...values };
      this.requested = { ...values };
      this.revision = revision;
      this.history.clear(revision);
      this.history.conflict = false;
      this.error = "";
      this.onChange();
    }
    dispose() {
      clearTimeout(this.timer);
      if (this.pending) this.finished = true;
      this._flush();
    }
  }
  function availableCameraNames(names, cameras, identity) {
    return names.filter((name) => !cameras.some((camera) =>
      camera.logical_name === name && camera.identity !== identity &&
      !camera.identity.startsWith("missing:")));
  }
  const api = { finiteText, NumberEdit, History, LiveTuner, availableCameraNames };
  root.SpotUI = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
