"""Check the CI release flags at the Windows native-process boundary."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell argument passing')
class ReleaseWorkflowTests(unittest.TestCase):
    def flags_for(self, tag):
        workflow = Path(__file__).resolve().parent.parent / '.github/workflows/beta.yml'
        assignment = next(line.strip() for line in workflow.read_text(encoding='utf-8').splitlines()
                          if line.strip().startswith('$channel ='))
        # Execute the actual workflow expression and inspect what a native program
        # receives. Splatting a scalar string sends individual characters.
        command = assignment + "; & $env:DUALTHEATER_RELEASE_TEST_PYTHON -c 'import json,sys; print(json.dumps(sys.argv[1:]))' @channel"
        environment = dict(os.environ, RELEASE_TAG=tag,
                           DUALTHEATER_RELEASE_TEST_PYTHON=sys.executable)
        shell = shutil.which('pwsh') or shutil.which('powershell')
        self.assertIsNotNone(shell, 'PowerShell is required to check release argument passing')
        result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, text=True, encoding='utf-8',
                                env=environment, timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_stable_release_passes_one_latest_flag(self):
        self.assertEqual(self.flags_for('v1.0.0'), ['--latest'])

    def test_beta_release_retains_prerelease_flags(self):
        self.assertEqual(self.flags_for('v1.0.1-beta.1'), ['--prerelease', '--latest=false'])
