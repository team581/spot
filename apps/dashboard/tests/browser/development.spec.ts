import { test, expect } from '@playwright/test';
test('development proxy keeps real same-origin writes and shared geometry working', async ({ page }) => {
	const errors: string[] = [];
	page.on('pageerror', (error) => errors.push(error.message));
	await page.goto('/');
	await expect(page.locator('.tile')).toHaveCount(4);
	await page.locator('.tile').first().click();
	const gain = page.getByRole('slider', { name: 'Gain', exact: true });
	await expect(gain).toBeEnabled();
	const initial = Number(await gain.inputValue());
	await gain.focus();
	await gain.press('ArrowRight');
	await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeEnabled();
	await expect(gain).toHaveValue(String(initial + 1));
	await page.getByRole('link', { name: 'Mount', exact: true }).click();
	await page.getByRole('checkbox', { name: 'Inspection preview' }).check();
	await expect(page.getByRole('textbox', { name: 'X', exact: true })).toHaveValue('0.31');
	expect(errors).toEqual([]);
});
