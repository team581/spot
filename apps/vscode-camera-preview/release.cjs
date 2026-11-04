const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const cp = require('node:child_process');
const version = require('./package.json').version;
const repository = 'team581/spot-2026';
const tag = `camera-preview-v${version}`;
const asset = `spot-camera-preview-${version}.vsix`;
const filename = path.join(__dirname, asset);
const gh = (args) => cp.execFileSync('gh', args, { encoding: 'utf8' });
if (!JSON.parse(gh(['repo', 'view', repository, '--json', 'isPrivate'])).isPrivate)
	throw Error('Refusing to publish outside a private repository');
const sha256 = crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
const checksum = filename + '.sha256';
fs.writeFileSync(checksum, `${sha256}  ${asset}\n`);
const notes = path.join(__dirname, 'release-notes.txt');
fs.writeFileSync(
	notes,
	`Private Team 581 camera preview ${version}.\n\nInstall from VSIX or use the robot build installer with the matching approved manifest.\n\nOffline compiled Java mount inspection with explicit Java/Jetson pitch conventions, signed-coordinate regression tests, and a toggleable adjustable 30-inch drivebase footprint. Automatic save refresh and private build-time updates.\n`,
);
gh([
	'release',
	'create',
	tag,
	filename,
	checksum,
	'--repo',
	repository,
	'--title',
	`Spot Camera Preview ${version}`,
	'--notes-file',
	notes,
]);
for (const root of [
	path.resolve(__dirname, '../robot-tester'),
	path.resolve(__dirname, '../../../offseason-2026/offseason-bot'),
]) {
	fs.writeFileSync(
		path.join(root, 'camera-preview-release.json'),
		JSON.stringify({ repository, tag, extensionId: 'team581.spot-camera-preview', version, asset, sha256 }, null, 2) +
			'\n',
	);
}
fs.unlinkSync(notes);
console.log(`Published ${tag}; both local project manifests pinned to ${sha256}`);
