"""Interrupted mutations must finish stopping their own descendant processes."""

import contextlib
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from flagship import cli


@unittest.skipUnless(sys.platform == "linux", "Process-group supervision requires Linux")
class ProcessSupervisionTests(unittest.TestCase):
    def exercise_signal(self, signum):
        with tempfile.TemporaryDirectory(prefix="flagship-supervise-tests-") as directory:
            root = Path(directory)
            ready, marker, leader = root / "ready", root / "late-write", root / "leader"
            descendant = root / "descendant.py"
            descendant.write_text("\n".join([
                "import signal, sys, time", "from pathlib import Path",
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
                "signal.signal(signal.SIGINT, signal.SIG_IGN)",
                "Path(sys.argv[1]).write_text('ready')", "time.sleep(4)",
                "Path(sys.argv[2]).write_text('survivor wrote this')", "time.sleep(30)",
            ]))
            worker = root / "worker.py"
            worker.write_text("\n".join([
                "import os, subprocess, sys", "from pathlib import Path",
                "Path(sys.argv[1]).write_text(str(os.getpid()))",
                "child = subprocess.Popen([sys.executable, sys.argv[2], sys.argv[3], sys.argv[4]])",
                "child.wait()",
            ]))
            supervisor = "\n".join([
                "import sys", f"sys.path.insert(0, {str(Path(cli.__file__).resolve().parents[1])!r})",
                "from flagship.cli import stream",
                "raise SystemExit(stream(sys.argv[1:], supervise=True))",
            ])
            process = subprocess.Popen(
                [sys.executable, "-c", supervisor, sys.executable, str(worker), str(leader), str(descendant), str(ready), str(marker)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "helper did not reach supervised execution")
                ready_time = time.monotonic()
                process.send_signal(signum)
                stdout, stderr = process.communicate(timeout=7)
                self.assertEqual(process.returncode, 128 + signum, stdout + stderr)
                # Cross the descendant's scheduled write deadline. Ignored
                # TERM/INT must have escalated to group termination by then.
                remaining = 4.3 - (time.monotonic() - ready_time)
                if remaining > 0:
                    time.sleep(remaining)
                self.assertFalse(marker.exists(), "interrupted mutation left a descendant running")
            finally:
                if process.poll() is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                if leader.exists():
                    # This PGID belongs only to the helper started above.
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(int(leader.read_text()), signal.SIGKILL)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()

    def test_termination_stops_signal_ignoring_descendant_before_return(self):
        self.exercise_signal(signal.SIGTERM)

    def test_interrupt_stops_signal_ignoring_descendant_before_return(self):
        self.exercise_signal(signal.SIGINT)


if __name__ == "__main__":
    unittest.main()
