import plistlib
import tempfile
import unittest
from pathlib import Path

from sideband.bundle import AGENT_LABEL, agent_plist, info_plist, launcher_script, write_app
from sideband.status import status_line, summary_line
from sideband.watchdog import Hold, on_packet


class BundleTest(unittest.TestCase):
    def test_info_plist_carries_bluetooth_reason(self) -> None:
        info = info_plist("0.2.0")
        self.assertTrue(info["NSBluetoothAlwaysUsageDescription"])
        self.assertTrue(info["LSUIElement"])

    def test_launcher_execs_quoted_python(self) -> None:
        text = launcher_script(Path("/a b/python"))
        self.assertIn("exec '/a b/python' -m sideband \"$@\"", text)
        self.assertIn("SIDEBAND_PIDFILE", text)

    def test_agent_runs_the_app_launcher(self) -> None:
        plist = agent_plist(Path("/A/Sideband.app"), "ID-1", Path("/logs"))
        self.assertEqual(plist["Label"], AGENT_LABEL)
        self.assertEqual(plist["ProgramArguments"][0], "/A/Sideband.app/Contents/MacOS/Sideband")
        self.assertIn("ID-1", plist["ProgramArguments"])
        self.assertTrue(plist["KeepAlive"])

    def test_write_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Sideband.app"
            launcher = write_app(app, Path("/usr/bin/python3"), "0.2.0")
            self.assertTrue(launcher.stat().st_mode & 0o111)
            with (app / "Contents" / "Info.plist").open("rb") as handle:
                self.assertEqual(plistlib.load(handle)["CFBundleExecutable"], "Sideband")


class StatusTest(unittest.TestCase):
    def test_lines(self) -> None:
        state = Hold()
        for i in range(100):
            state = on_packet(state, i * 0.02).state
        line = status_line(state, 50, 1.0, 80)
        self.assertIn("frames=100 (+50, 50.0/s)", line)
        self.assertIn("battery=80%", line)
        self.assertIn("battery=unread", summary_line(state, None))


if __name__ == "__main__":
    unittest.main()
