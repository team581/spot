const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const version = require('./package.json').version;
const repository = 'team581/spot-2026';
const tag = `camera-preview-v${version}`;
const filename = path.join(__dirname, `spot-camera-preview-${version}.vsix`);
fs.accessSync(filename, fs.constants.R_OK);
const gh = (args) => cp.execFileSync('gh', args, { encoding: 'utf8' });
if (!JSON.parse(gh(['repo', 'view', repository, '--json', 'isPrivate'])).isPrivate)
	throw Error('Refusing to publish outside a private repository');
gh([
	'release',
	'create',
	tag,
	filename,
	'--repo',
	repository,
	'--title',
	`Spot Camera Preview ${version}`,
	'--notes',
	'In VS Code, use Extensions → … → Install from VSIX… to install this extension.',
]);
console.log(`Published ${tag}`);
