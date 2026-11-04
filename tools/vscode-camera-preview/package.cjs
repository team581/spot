// Use the official VSIX packager; never publishes to the Marketplace.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
fs.copyFileSync(path.resolve(__dirname, '../../src/spot_vision/web/viewer.js'), path.join(__dirname, 'media/viewer.js'));
const version = require('./package.json').version;
cp.execFileSync(process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm', ['exec', 'vsce', 'package', '--no-dependencies', '--allow-missing-repository', '--skip-license', '-o', `spot-camera-preview-${version}.vsix`], {stdio:'inherit'});
