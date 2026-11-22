"""install-local-ai-linux.sh on a machine without Ollama (2026-11-22).

`OCANDS=("$(command -v ollama)" ...)` under `set -e` ended the script the moment `command -v`
found nothing, so the installer stopped at "Step 2" with no message at all. It must instead
print where to put the Ollama archive and stop with "Ollama not available".
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "..", "install-local-ai-linux.sh")


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "needs bash")
class NoOllama(unittest.TestCase):
    def test_says_what_to_do(self):
        tmp = tempfile.mkdtemp(prefix="no-ollama-")
        try:
            env = {"HOME": tmp, "PATH": "/usr/bin:/bin", "LANG": "C"}
            if shutil.which("ollama", path=env["PATH"]):
                self.skipTest("ollama is installed in /usr/bin or /bin here")
            p = subprocess.run(["bash", SCRIPT, "--prefix=" + os.path.join(tmp, "sbx"), "--no-models"],
                               cwd=os.path.dirname(SCRIPT), env=env, capture_output=True, text=True, timeout=120)
            out = p.stdout + p.stderr
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("No Ollama found", out)
            self.assertIn("Ollama not available", out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
