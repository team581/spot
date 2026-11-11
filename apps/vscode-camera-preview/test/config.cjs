const test = require('node:test');
const assert = require('node:assert/strict');
const { parseConfig } = require('../config.ts');

void test('cameras keyed by name become preview cameras with schema defaults', () => {
	const cameras = parseConfig(`
#:schema https://spot.frc581.com/spot-config.schema.json
tag_size = 0.1651
ignored_tags = [3]
[recording]
image_fps = 30
[cameras.front]
serial = "ABC123"
required = true
mode = "640x480@30"
controls = { auto_exposure = "manual", exposure_time_absolute = 50, gain = 10 }
mount = { x = 0.3, y = -0.1, z = 0.25, pitch = -15 }
[cameras.front.calibrations.1280x800]
fx = 900.0
fy = 900.0
cx = 640.0
cy = 400.0
distortion = [0, 0, 0, 0, 0]
[cameras.back]
port = "usb1"
`);
	assert.deepEqual(
		cameras.map((c) => c.name),
		['front', 'back'],
	);
	const [front, back] = cameras;
	assert.equal(front.required, true);
	assert.equal(front.serial, 'ABC123');
	assert.equal(front.resolution, '640x480');
	assert.deepEqual(front.mount, { x: 0.3, y: -0.1, z: 0.25, roll: 0, pitch: -15, yaw: 0 });
	assert.deepEqual(front.calibrations, ['1280x800']);
	assert.equal(front.controls.exposure_time_absolute, 50);
	assert.equal(back.required, false);
	assert.equal(back.port, 'usb1');
	assert.equal(back.mode, '1280x800@120');
	assert.equal(back.resolution, '1280x800');
	assert.deepEqual(back.mount, { x: 0, y: 0, z: 0, roll: 0, pitch: 0, yaw: 0 });
	assert.deepEqual(back.calibrations, []);
});

void test('a config without cameras previews no cameras', () => {
	assert.deepEqual(parseConfig('tag_size = 0.1651'), []);
	assert.deepEqual(parseConfig(''), []);
});

void test('malformed configs give readable errors naming the bad key', () => {
	const cases = {
		'[cameras.front]\nmount = { x = }': /invalid value[^]*2: +mount/,
		'cameras = 3': /^cameras must be a table/,
		'cameras.front = "usb1"': /^cameras\.front must be a table/,
		'[cameras.front]\nmout = { x = 1 }': /^cameras\.front has unknown key "mout"/,
		'[cameras.front]\nmount = { x = "0.3" }': /^cameras\.front\.mount\.x must be a number/,
		'[cameras.front]\nmount = { pitch_deg = 10 }': /^cameras\.front\.mount has unknown key "pitch_deg"/,
		'[cameras.front]\nmode = "1280x800"': /^cameras\.front\.mode must look like 1280x800@120/,
		'[cameras.front]\nrequired = "yes"': /^cameras\.front\.required must be a boolean/,
		'[cameras.front]\ncontrols = { exposure = 5 }': /^cameras\.front\.controls has unknown key "exposure"/,
	};
	for (const [text, message] of Object.entries(cases)) assert.throws(() => parseConfig(text), { message }, text);
});
