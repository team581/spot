import * as fs from 'node:fs';
import * as path from 'node:path';
/** The robot project's spot-config.json for an opened spot-config.json or VisionConfig.java. */
export function discover(file: string) {
	if (path.basename(file) === 'spot-config.json') return file;
	let dir = path.dirname(file);
	while (!fs.existsSync(path.join(dir, 'build.gradle'))) {
		const parent = path.dirname(dir);
		if (parent === dir) throw Error('No Gradle project found for this file');
		dir = parent;
	}
	return path.join(dir, 'src/main/deploy/spot-config.json');
}
