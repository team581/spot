import { expect, test } from 'vite-plus/test';
import { diffOverrides, setOverride } from './overrides';

test('setOverride sets nested values without touching siblings or the input', () => {
	const overrides = { ignored_tags: [3], cameras: { front: { serial: 'A', mount: { x: 1 } } } };
	const next = setOverride(overrides, ['cameras', 'front', 'mount', 'y'], 2);
	expect(next).toEqual({ ignored_tags: [3], cameras: { front: { serial: 'A', mount: { x: 1, y: 2 } } } });
	expect(overrides.cameras.front.mount).toEqual({ x: 1 });
});

test('setOverride replaces a removed camera with an object to write into', () => {
	expect(setOverride({ cameras: { front: null } }, ['cameras', 'front', 'port'], 'usb1')).toEqual({
		cameras: { front: { port: 'usb1' } },
	});
});

test('diffOverrides pairs leaf overrides with robot values', () => {
	const robot = { cameras: { front: { serial: 'A', controls: { gain: 5 } } } };
	const overrides = {
		cameras: { front: { serial: null, port: 'usb1', controls: { gain: 7 } }, back: { serial: 'B' } },
	};
	expect(diffOverrides(robot, overrides)).toEqual([
		{ path: 'cameras.front.serial', before: 'A', after: null },
		{ path: 'cameras.front.port', before: undefined, after: 'usb1' },
		{ path: 'cameras.front.controls.gain', before: 5, after: 7 },
		{ path: 'cameras.back.serial', before: undefined, after: 'B' },
	]);
});
