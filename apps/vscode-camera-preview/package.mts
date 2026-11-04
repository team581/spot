import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string };
execFileSync(
	process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm',
	['exec', 'vsce', 'package', '--no-dependencies', '-o', `spot-camera-preview-${version}.vsix`],
	{ stdio: 'inherit' },
);
