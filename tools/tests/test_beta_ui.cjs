const test = require("node:test");
const assert = require("node:assert/strict");
const {
  NumberEdit,
  History,
  LiveTuner,
  finiteText,
  availableCameraNames,
} = require("../../src/spot_vision/web/ui-state.js");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("numeric text stays exact through deletion, typing and theme-independent preview", async () => {
  const previews = [],
    writes = [];
  const edit = new NumberEdit(0.31, {
    revision: "a",
    preview: (v) => previews.push(v),
    commit: async (v, r) => {
      writes.push([v, r]);
      return { value: v, revision: "b" };
    },
  });
  edit.focus();
  edit.input("0.3");
  edit.input("0.38");
  assert.equal(edit.text, "0.38");
  assert.deepEqual(previews, [0.3, 0.38]);
  assert.equal(await edit.commit(), true);
  assert.equal(await edit.commit(), false);
  assert.deepEqual(writes, [[0.38, "a"]]);
  assert.equal(edit.text, "0.38");
});
test("intermediate and invalid text never writes; Escape restores acknowledged value", async () => {
  const edit = new NumberEdit(1, {
    min: -2,
    max: 2,
    commit: async () => assert.fail("invalid write"),
  });
  for (const text of ["", "-", ".", "NaN", "Infinity", "1e9", "3"]) {
    edit.input(text);
    assert.equal(await edit.commit(), false);
  }
  edit.cancel();
  assert.equal(edit.text, "1");
  assert.equal(finiteText("-.2"), true);
});
test("failed Enter followed by blur makes only one request until edit changes", async () => {
  let count = 0;
  const edit = new NumberEdit(1, {
    commit: async () => {
      count++;
      throw new Error("device rejected");
    },
  });
  edit.focus();
  edit.input("2");
  await edit.commit();
  edit.focused = false;
  await edit.commit();
  assert.equal(count, 1);
  assert.equal(edit.ack, 1);
  edit.input("3");
  await edit.commit();
  assert.equal(count, 2);
});
test("external revision preserves focused buffer and blocks stale commit", async () => {
  const edit = new NumberEdit(1, {
    revision: "a",
    commit: async () => assert.fail("stale write"),
  });
  edit.focus();
  edit.input("1.23");
  edit.readback(2, "b");
  assert.equal(edit.text, "1.23");
  assert.equal(edit.conflict, true);
  assert.equal(await edit.commit(), false);
  edit.cancel();
  assert.equal(edit.text, "2");
});
test("translation and angle steppers obey exact modifier increments", () => {
  const edit = new NumberEdit(0.3);
  edit.step(1);
  assert.equal(edit.text, "0.31");
  edit.step(-1, { altKey: true });
  assert.equal(edit.text, "0.309");
  edit.step(1, { shiftKey: true });
  assert.equal(edit.text, "0.409");
  edit.input("10");
  edit.step(1, { altKey: true }, true);
  assert.equal(edit.text, "10.1");
  edit.step(-1, { shiftKey: true }, true);
  assert.equal(edit.text, "0.1");
});
test("history changes stacks only after successful acknowledged transaction", async () => {
  const history = new History();
  history.record({ gain: 1 }, { gain: 3 }, "a");
  await assert.rejects(
    history.apply("undo", async () => {
      throw new Error("readback failed");
    }),
  );
  assert.equal(history.undoStack.length, 1);
  assert.equal(history.redoStack.length, 0);
  await history.apply("undo", async (values) => {
    assert.deepEqual(values, { gain: 1 });
    return { revision: "b" };
  });
  assert.equal(history.redoStack.length, 1);
  history.observe("external");
  assert.equal(history.conflict, true);
  assert.equal(history.undoStack.length + history.redoStack.length, 0);
});
test("one slider drag serializes, coalesces final value and creates one history entry", async () => {
  let active = 0,
    maxActive = 0;
  const writes = [];
  const tuner = new LiveTuner({ gain: 1 }, "a", async (values) => {
    active++;
    maxActive = Math.max(maxActive, active);
    writes.push(values.gain);
    await wait(30);
    active--;
    return { revision: String(writes.length), values };
  });
  tuner.request("gain", 2);
  await wait(10);
  tuner.request("gain", 3);
  tuner.request("gain", 4, true);
  tuner.end();
  await wait(330);
  assert.equal(maxActive, 1);
  assert.equal(writes.at(-1), 4);
  assert.equal(tuner.values.gain, 4);
  assert.equal(tuner.history.undoStack.length, 1);
  assert.deepEqual(tuner.history.undoStack[0], {
    before: { gain: 1 },
    after: { gain: 4 },
  });
  tuner.dispose();
});
test("conflicted live write leaves no misleading undo transaction", async () => {
  const tuner = new LiveTuner({ gain: 1 }, "a", async () => {
    throw new Error("Revision conflict");
  });
  tuner.request("gain", 2, true);
  await wait(30);
  assert.equal(tuner.history.conflict, true);
  assert.equal(tuner.history.undoStack.length, 0);
  assert.equal(tuner.values.gain, 1);
  tuner.dispose();
});

test("Auto theme follows OS changes; manual preference survives reload", () => {
  const vm = require("node:vm");
  const fs = require("node:fs");
  const code = fs.readFileSync(
    require.resolve("../../src/spot_vision/web/theme.js"),
    "utf8",
  );
  const saved = new Map();
  function load(matches) {
    const media = {
      matches,
      addEventListener: (_, callback) => {
        media.changed = callback;
      },
    };
    const document = { documentElement: { dataset: {} } };
    const window = {};
    vm.runInNewContext(code, {
      document,
      window,
      localStorage: {
        getItem: (key) => saved.get(key),
        setItem: (key, value) => saved.set(key, value),
      },
      matchMedia: () => media,
      dispatchEvent: () => {},
      CustomEvent: class {},
    });
    return { media, document, window };
  }
  const first = load(false);
  assert.equal(first.window.SpotTheme.get(), "Auto");
  assert.equal(first.document.documentElement.dataset.theme, "light");
  first.media.matches = true;
  first.media.changed();
  assert.equal(first.document.documentElement.dataset.theme, "dark");
  first.window.SpotTheme.set("Light");
  first.media.changed();
  assert.equal(first.document.documentElement.dataset.theme, "light");
  const reloaded = load(true);
  assert.equal(reloaded.window.SpotTheme.get(), "Light");
  assert.equal(reloaded.document.documentElement.dataset.theme, "light");
});

test("unbound role placeholders remain pairable while disconnected real bindings stay reserved", () => {
  const names = ["front", "back", "side"];
  const cameras = [
    {identity: "missing:front", logical_name: "front", present: false},
    {identity: "missing:side", logical_name: "side", present: false},
    {identity: "physical-back", logical_name: "back", present: false},
    {identity: "physical-front", present: true},
  ];
  assert.deepEqual(availableCameraNames(names, cameras, "physical-front"), ["front", "side"]);
  assert.deepEqual(availableCameraNames(names, cameras, "physical-back"), names);
});
