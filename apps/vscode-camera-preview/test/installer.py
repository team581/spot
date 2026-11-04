"""Exercise the actual Gradle installer with isolated fake editor/release CLIs."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class InstallerTest(unittest.TestCase):
    def test_install_update_and_failure_paths(self):
        with tempfile.TemporaryDirectory(prefix="spot installer ") as name:
            root = Path(name)
            shutil.copy(ROOT / "apps/robot-tester/camera-preview.gradle", root)
            (root / "settings.gradle").write_text("rootProject.name='installer-test'\n")
            (root / "build.gradle").write_text(
                "plugins { id 'base' }; apply from: 'camera-preview.gradle'\n"
            )
            payload = b"test-vsix"
            manifest = dict(
                repository="private/test",
                tag="v1",
                extensionId="team581.spot-camera-preview",
                version="0.1.0",
                asset="preview.vsix",
                sha256=hashlib.sha256(payload).hexdigest(),
            )
            (root / "camera-preview-release.json").write_text(json.dumps(manifest))
            code = root / "code"
            code.write_text("""#!/usr/bin/env python3
import os,sys
from pathlib import Path
root=Path(__file__).parent
if '--list-extensions' in sys.argv:
 print('team581.spot-camera-preview@'+(root/'installed').read_text())
else:
 assert '--force' in sys.argv
 with (root/'calls').open('a') as f:f.write('installed\\n')
""")
            gh = root / "gh"
            gh.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
root=Path(__file__).parent
if (root/'fail').exists(): sys.exit(1)
out=Path(sys.argv[sys.argv.index('--dir')+1])
(out/'preview.vsix').write_bytes((root/'payload').read_bytes())
""")
            code.chmod(0o755)
            gh.chmod(0o755)
            (root / "payload").write_bytes(payload)
            (root / "installed").write_text("0.1.0")
            cache = Path.home() / ".gradle/spot-camera-preview" / (manifest["sha256"] + ".vsix")

            def run(task="installSpotCameraPreview", props=(), env_extra=None):
                env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"])
                for key in ("CI", "SSH_CONNECTION", "SSH_TTY"):
                    env.pop(key, None)
                env.update(env_extra or {})
                result = subprocess.run(
                    [
                        str(ROOT / "apps/robot-tester/gradlew"),
                        "-p",
                        str(root),
                        task,
                        "--console=plain",
                        "-PspotCameraPreviewCode=" + str(code),
                        *props,
                    ],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                return result

            try:
                # Current and newer versions never install or download.
                self.assertEqual(run().returncode, 0)
                (root / "installed").write_text("0.2.0")
                self.assertEqual(run().returncode, 0)
                self.assertFalse((root / "calls").exists())
                # Missing/older version downloads and verifies; a second run uses the cache offline.
                (root / "installed").write_text("0.0.1")
                self.assertEqual(run().returncode, 0)
                self.assertTrue((root / "calls").exists())
                (root / "fail").touch()
                self.assertEqual(run().returncode, 0)
                cache.unlink(missing_ok=True)
                self.assertNotEqual(run().returncode, 0)
                self.assertEqual(run("build").returncode, 0)
                # Skip cases must not invoke even a missing editor.
                for extra in ({"CI": "true"}, {"SSH_CONNECTION": "test"}):
                    self.assertEqual(run(env_extra=extra).returncode, 0)
                self.assertEqual(run(props=["-PskipSpotCameraPreviewInstall=true"]).returncode, 0)
                # A bad release asset must not install.
                (root / "fail").unlink()
                (root / "payload").write_bytes(b"corrupt")
                result = run()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("checksum mismatch", result.stdout)
            finally:
                cache.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
