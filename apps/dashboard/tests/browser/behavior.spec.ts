import { test, expect, type BrowserContext } from '@playwright/test';
let cookies: Awaited<ReturnType<BrowserContext['cookies']>> | undefined;

test.beforeEach(async ({ page, context }) => {
	if (cookies) await context.addCookies(cookies);
	else {
		await page.request.get('/api/session');
		cookies = await context.cookies();
	}
	page.on('pageerror', (error) => {
		throw error;
	});
});

test('navigation, images, detections, pause and geometry inspection', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible();
	await expect(page.locator('.tile')).toHaveCount(4);
	await page.locator('.tile').first().click();
	await expect(page.getByRole('heading', { name: 'front-left', exact: true })).toBeVisible();
	await expect(page.locator('#detections')).toContainText('3.1 m');
	await page.getByRole('button', { name: 'Pause image', exact: true }).click();
	await expect(page.locator('.image-state')).toContainText('Paused');
	await page.getByRole('button', { name: 'Resume image', exact: true }).click();
	await page.getByRole('link', { name: 'Geometry', exact: true }).click();
	await expect(page.getByRole('textbox', { name: 'X', exact: true })).toBeDisabled();
	await page.getByLabel('Inspection preview').check();
	const x = page.getByRole('textbox', { name: 'X', exact: true });
	await x.fill('0.38');
	await x.press('Enter');
	await expect(page.locator('#transform-readout')).toContainText('X 0.380 m');
	await page.getByRole('button', { name: 'Reset to code defaults', exact: true }).click();
	await expect(x).toHaveValue('0.31');
	await page.getByRole('link', { name: 'System', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Camera pipelines' })).toBeVisible();
	await expect(page.locator('#software-data')).toContainText('development-fixture');
});

test('acknowledged tuning, undo, redo and reset use real session and jobs', async ({ page }) => {
	const status = await (await page.request.get('/api/status')).json();
	await page.goto('/#camera/' + status.cameras[0].identity);
	const gain = page.getByRole('slider', { name: 'Gain', exact: true });
	await expect(gain).toBeEnabled();
	const initial = await gain.inputValue();
	await gain.focus();
	await gain.press('ArrowRight');
	await expect(page.locator('[data-control="gain"] .readback')).toHaveText('Readback ' + (Number(initial) + 1) + ' ');
	await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeEnabled();
	await page.getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(gain).toHaveValue(initial);
	await page.getByRole('button', { name: 'Redo', exact: true }).click();
	await expect(gain).toHaveValue(String(Number(initial) + 1));
	await page.getByRole('button', { name: 'Reset to code defaults', exact: true }).click();
	await expect(gain).toHaveValue('30');
});

test('naming requires preview confirmation and reserves existing roles', async ({ page }) => {
	const status = await (await page.request.get('/api/status')).json();
	await page.goto('/#camera/' + status.cameras[3].identity);
	const rename = page.getByRole('button', { name: 'Rename', exact: true });
	await expect(rename).toBeDisabled();
	await expect(page.locator('#camera-name option')).toHaveText(['turret']);
	await page.getByLabel('This preview matches the physical camera').check();
	await expect(rename).toBeEnabled();
	// Keep the shared fixture unchanged; inspect the payload at the boundary.
	const request = page.waitForRequest((r) => r.url().endsWith('/api/operations'));
	await rename.click();
	const body = (await request).postDataJSON();
	expect(body.operation).toBe('rename');
	expect(body.payload.name).toBe('turret');
});

test('calibration actions and passing results require acknowledgement', async ({ page }) => {
	await page.goto('/#calibration');
	await expect(page.locator('.calibration-card')).toHaveCount(2);
	await page.getByRole('button', { name: 'Start automatic capture', exact: true }).click();
	await expect(
		page.locator('.calibration-card').first().getByRole('button', { name: 'Pause', exact: true }),
	).toBeVisible();
	await page.getByRole('button', { name: 'Pause all', exact: true }).click();
	await expect(
		page.locator('.calibration-card').first().getByRole('button', { name: 'Start', exact: true }),
	).toBeVisible();
	await page.getByRole('link', { name: 'Results / history', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Apply selected', exact: true })).toBeDisabled();
	await page.getByRole('button', { name: 'Select passing', exact: true }).click();
	await page.getByRole('button', { name: 'Apply selected', exact: true }).click();
	await expect(page.locator('#apply-status')).toContainText('Applied');
});

test('robot lock disables tuning and calibration', async ({ page }) => {
	const status = await (await page.request.get('/api/status')).json();
	status.lock_reason = 'Robot enabled · locked';
	await page.route('**/api/status', (route) => route.fulfill({ json: status }));
	await page.goto('/#camera/' + status.cameras[0].identity);
	await expect(page.getByRole('slider', { name: 'Gain', exact: true })).toBeDisabled();
	await expect(page.locator('#config-lock')).toHaveText(status.lock_reason);
	await page.goto('/#calibration/results');
	await page.getByRole('button', { name: 'Select passing', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Apply selected', exact: true })).toBeDisabled();
});

test('failed job leaves readback unchanged and no undo history', async ({ page }) => {
	const status = await (await page.request.get('/api/status')).json();
	await page.route('**/api/operations', (route) => route.fulfill({ json: { job_id: 'rejected' } }));
	await page.route('**/api/jobs/rejected', (route) =>
		route.fulfill({
			json: { state: 'rejected', error: 'Revision conflict; reconcile current values' },
		}),
	);
	await page.goto('/#camera/' + status.cameras[0].identity);
	const gain = page.getByRole('slider', { name: 'Gain', exact: true });
	await gain.focus();
	await gain.press('ArrowRight');
	await expect(page.locator('#control-feedback')).toContainText('Revision conflict');
	await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeDisabled();
	await expect(page.getByRole('button', { name: 'Reconcile current values' })).toBeVisible();
	await page.getByRole('button', { name: 'Reconcile current values' }).click();
	await expect(gain).toBeEnabled();
	await expect(gain).toHaveValue('30');
});

test('network apply payload and confirmation token', async ({ page }) => {
	const status = await (await page.request.get('/api/status')).json();
	status.network = {
		available: true,
		hostname: 'spot.local',
		interfaces: [{ interface: 'eth0', addresses: ['10.5.81.11/24'], mode: 'static' }],
	};
	const writes: unknown[] = [];
	await page.route('**/api/status', (route) => route.fulfill({ json: status }));
	await page.route('**/api/operations', async (route) => {
		const body = route.request().postDataJSON();
		writes.push(body);
		if (body.operation === 'network/apply')
			status.network.pending = {
				token: 'a'.repeat(32),
				interface: 'eth0',
				address: body.payload.address,
				remaining_s: 89,
			};
		else delete status.network.pending;
		await route.fulfill({ json: { job_id: 'network' } });
	});
	await page.route('**/api/jobs/network', (route) => route.fulfill({ json: { state: 'applied' } }));
	await page.goto('/#network');
	await page.getByLabel('Ethernet port').selectOption('eth0');
	await page.getByLabel('IPv4 address / prefix').fill('10.5.81.12/24');
	await page.getByRole('button', { name: 'Apply for 90 seconds', exact: true }).click();
	await expect(page.locator('#network-countdown')).toContainText('89 seconds');
	await page.getByRole('button', { name: 'Keep settings', exact: true }).click();
	await expect(page.locator('#network-feedback')).toContainText('saved for future boots');
	expect(writes).toEqual([
		expect.objectContaining({
			operation: 'network/apply',
			payload: { interface: 'eth0', mode: 'static', address: '10.5.81.12/24' },
		}),
		expect.objectContaining({ operation: 'network/confirm', payload: { token: 'a'.repeat(32) } }),
	]);
});

test('theme preference survives navigation and reload', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('button', { name: 'Theme: Auto', exact: true }).click();
	await page.getByRole('menuitemradio', { name: 'Dark', exact: true }).click();
	await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
	await page.reload();
	await expect(page.getByRole('button', { name: 'Theme: Dark', exact: true })).toBeVisible();
});

test('empty inventory and service disconnect show explicit states', async ({ page }) => {
	const status = await (await page.request.get('/api/status')).json();
	status.cameras = [];
	let disconnected = false;
	await page.route('**/api/status', (route) => (disconnected ? route.abort() : route.fulfill({ json: status })));
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'No cameras discovered' })).toBeVisible();
	disconnected = true;
	await expect(page.locator('#announcement')).toContainText('Service unavailable');
});

test('stale frames hide detections and disconnect retains a labelled last image', async ({ page }) => {
	const status = await (await page.request.get('/api/status')).json();
	let stale = false,
		offline = false;
	await page.route('**/api/status', (route) => (offline ? route.abort() : route.fulfill({ json: status })));
	await page.route('**/api/frame/**', async (route) => {
		const response = await route.fetch();
		const frame = await response.json();
		if (stale) frame.stale = true;
		await route.fulfill({ json: frame });
	});
	await page.goto('/#camera/' + status.cameras[0].identity);
	await expect(page.locator('#detections')).toContainText('3.1 m');
	stale = true;
	await expect(page.locator('#detections')).toContainText('Waiting for current detection frame');
	await expect(page.locator('.image-state')).toContainText('Stale image');
	offline = true;
	await expect(page.locator('.image-state')).toContainText('Service disconnected');
});

test('geometry editing preserves intermediate text through polling and never writes production geometry', async ({
	page,
}) => {
	const status = await (await page.request.get('/api/status')).json(),
		writes: unknown[] = [];
	page.on('request', (r) => {
		if (r.url().endsWith('/api/operations')) writes.push(r.postDataJSON());
	});
	await page.goto('/#camera/' + status.cameras[0].identity + '/geometry');
	await page.getByLabel('Inspection preview').check();
	const x = page.getByRole('textbox', { name: 'X', exact: true });
	await x.fill('-');
	await page.waitForTimeout(700);
	await expect(x).toHaveValue('-');
	await x.press('Enter');
	await expect(page.locator('#geometry-fields')).toContainText('Enter a finite value');
	await x.press('Escape');
	await expect(x).toHaveValue('0.31');
	await x.press('Alt+ArrowUp');
	await expect(x).toHaveValue('0.311');
	expect(writes).toEqual([]);
});

test('board drafts survive polls and calibration sends the selected capture phase', async ({ page }) => {
	const writes: { operation: string; payload: Record<string, unknown> }[] = [];
	await page.route('**/api/operations', async (route) => {
		writes.push(route.request().postDataJSON());
		await route.fulfill({ json: { job_id: 'capture' } });
	});
	await page.route('**/api/jobs/capture', (route) =>
		route.fulfill({ json: { state: 'applied', revision: 'fixture' } }),
	);
	await page.goto('/#calibration');
	const x = page.getByLabel('Squares X', { exact: true });
	await x.fill('17');
	await page.waitForTimeout(700);
	await expect(x).toHaveValue('17');
	await page.getByRole('button', { name: 'Update board', exact: true }).click();
	await expect.poll(() => writes.filter((w) => w.operation === 'calibration/board').length).toBe(1);
	expect(writes.find((w) => w.operation === 'calibration/board')?.payload.board).toEqual(
		expect.objectContaining({ squares_x: 17 }),
	);
	const card = page.locator('.calibration-card').first();
	await card.getByLabel('Capture set').selectOption('holdout');
	await card.getByRole('button', { name: 'Capture', exact: true }).click();
	await expect.poll(() => writes.filter((w) => w.operation === 'calibration/capture').length).toBe(1);
	expect(writes.find((w) => w.operation === 'calibration/capture')?.payload).toEqual(
		expect.objectContaining({ phase: 'holdout', automatic: true }),
	);
});

test('failed calibration validation cannot be selected for apply; compatible history restores selected hashes', async ({
	page,
}) => {
	const status = await (await page.request.get('/api/status')).json(),
		writes: unknown[] = [];
	await page.route('**/api/operations', async (route) => {
		writes.push(route.request().postDataJSON());
		await route.fulfill({ json: { job_id: 'restore' } });
	});
	await page.route('**/api/jobs/restore', (route) =>
		route.fulfill({ json: { state: 'applied', revision: status.revision } }),
	);
	await page.goto('/#calibration/results');
	const checkboxes = page.locator('table input[type=checkbox]');
	await checkboxes.nth(1).check();
	await expect(page.getByRole('button', { name: 'Apply selected', exact: true })).toBeDisabled();
	await page.locator('.history-panel input[type=checkbox]').first().check();
	await page.getByRole('button', { name: 'Restore selected', exact: true }).click();
	await expect.poll(() => writes.length).toBe(1);
	expect(writes[0]).toEqual(
		expect.objectContaining({
			operation: 'restore',
			payload: expect.objectContaining({
				generation: 'fixture-previous-calibration',
				calibration_hashes: ['fixture-record-0'],
			}),
		}),
	);
});

test('automatic network rollback restores the form; explicit revert uses the confirmation token', async ({ page }) => {
	const status = await (await page.request.get('/api/status')).json();
	status.network = {
		available: true,
		interfaces: [{ interface: 'eth0', addresses: ['10.5.81.11/24'], mode: 'static' }],
	};
	const writes: { operation: string; payload: unknown }[] = [];
	await page.route('**/api/status', (route) => route.fulfill({ json: status }));
	await page.route('**/api/operations', async (route) => {
		const body = route.request().postDataJSON();
		writes.push(body);
		if (body.operation === 'network/apply')
			status.network.pending = {
				token: 'b'.repeat(32),
				interface: 'eth0',
				address: body.payload.address,
				remaining_s: 30,
			};
		else delete status.network.pending;
		await route.fulfill({ json: { job_id: 'rollback' } });
	});
	await page.route('**/api/jobs/rollback', (route) => route.fulfill({ json: { state: 'applied' } }));
	await page.goto('/#network');
	await page.getByLabel('Ethernet port').selectOption('eth0');
	await page.getByLabel('IPv4 address / prefix').fill('10.5.81.99/24');
	await page.getByRole('button', { name: 'Apply for 90 seconds', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Revert now', exact: true })).toBeVisible();
	delete status.network.pending;
	await expect(page.getByLabel('IPv4 address / prefix')).toHaveValue('10.5.81.11/24');
	await page.getByRole('button', { name: 'Apply for 90 seconds', exact: true }).click();
	await page.getByRole('button', { name: 'Revert now', exact: true }).click();
	await expect(page.locator('#network-feedback')).toContainText('Previous connection restored');
	expect(writes.at(-1)).toEqual(
		expect.objectContaining({ operation: 'network/revert', payload: { token: 'b'.repeat(32) } }),
	);
});

test('system downloads, import bound and diagnostics preserve their API contracts', async ({ page }) => {
	const writes: { operation: string; payload: Record<string, unknown> }[] = [];
	await page.route('**/api/export', (route) => route.fulfill({ json: { schema_version: 2, cameras: {} } }));
	await page.route('**/api/operations', async (route) => {
		writes.push(route.request().postDataJSON());
		await route.fulfill({ json: { job_id: 'system' } });
	});
	await page.route('**/api/jobs/system', (route) => route.fulfill({ json: { state: 'applied' } }));
	await page.goto('/#system');
	const download = page.waitForEvent('download');
	await page.getByRole('button', { name: 'Export configuration', exact: true }).click();
	expect((await download).suggestedFilename()).toBe('spot-state.json');
	const file = page.locator('input[type=file]');
	await file.setInputFiles({
		name: 'oversized.json',
		mimeType: 'application/json',
		buffer: Buffer.alloc(2 * 1024 * 1024 + 1),
	});
	await expect(page.locator('#page-feedback')).toContainText('exceeds 2 MiB');
	expect(writes).toEqual([]);
	await file.setInputFiles({
		name: 'state.json',
		mimeType: 'application/json',
		buffer: Buffer.from('{"schema_version":2}'),
	});
	await expect.poll(() => writes.length).toBe(1);
	expect(writes[0].payload.document).toEqual({ schema_version: 2 });
	await page.getByRole('button', { name: 'Record 10 s diagnostics', exact: true }).click();
	await expect.poll(() => writes.length).toBe(2);
	expect(writes[1]).toEqual(
		expect.objectContaining({ operation: 'debug', payload: expect.objectContaining({ seconds: 10 }) }),
	);
});

test('mode and replacement operations use the camera identity and require feed confirmation', async ({ page }) => {
	const status = await (await page.request.get('/api/status')).json(),
		writes: { operation: string; payload: unknown }[] = [];
	status.cameras[0].allowed_modes.push({
		...status.cameras[0].allowed_modes[0],
		id: '1280x720',
		width: 1280,
		height: 720,
	});
	await page.route('**/api/status', (route) => route.fulfill({ json: status }));
	await page.route('**/api/operations', async (route) => {
		writes.push(route.request().postDataJSON());
		await route.fulfill({ json: { job_id: 'camera' } });
	});
	await page.route('**/api/jobs/camera', (route) =>
		route.fulfill({ json: { state: 'applied', revision: status.revision } }),
	);
	await page.goto('/#camera/' + status.cameras[0].identity);
	await page.getByText('Advanced', { exact: true }).click();
	await page.getByLabel('Capture resolution / rate').selectOption('1280x720');
	await expect.poll(() => writes.length).toBe(1);
	expect(writes[0]).toEqual(
		expect.objectContaining({
			operation: 'mode',
			payload: expect.objectContaining({ name: 'front-left', mode_id: '1280x720' }),
		}),
	);
	// Applying a mode remounts the form; wait before interacting with the replacement controls.
	await expect(page.getByRole('button', { name: 'Replace camera', exact: true })).toBeHidden();
	await page.getByText('Advanced', { exact: true }).click();
	await page.getByRole('button', { name: 'Replace camera', exact: true }).click();
	await expect(page.locator('#page-feedback')).toContainText('Identify the replacement feed');
	expect(writes).toHaveLength(1);
	await page.getByLabel('I confirmed the replacement feed').check();
	await page.getByRole('button', { name: 'Replace camera', exact: true }).click();
	await expect.poll(() => writes.length).toBe(2);
	expect(writes[1]).toEqual(
		expect.objectContaining({
			operation: 'replace',
			payload: expect.objectContaining({ identity: status.cameras[0].identity, name: 'front-left' }),
		}),
	);
});
