const fs = require('node:fs');
const path = require('node:path');
function discover(file) {
  let dir = path.dirname(file);
  while (true) {
    if (fs.existsSync(path.join(dir, 'build.gradle'))) {
      const project = dir;
      let root = dir;
      while (!fs.existsSync(path.join(root, 'gradlew'))) {
        const parent = path.dirname(root);
        if (parent === root) throw Error('Gradle wrapper not found');
        root = parent;
      }
      return {project, root, task: (project === root ? '' : ':' + path.relative(root, project).split(path.sep).join(':') + ':') + 'exportSpotCameraPreview'};
    }
    const parent = path.dirname(dir);
    if (parent === dir) throw Error('No Gradle project found for this file');
    dir = parent;
  }
}
module.exports = {discover};
