"""The Python application. The command line and launchd both call this object."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from sideband import __version__
from sideband.audio import WavSink
from sideband.bundle import (
    AGENT_LABEL,
    agent_plist,
    default_agent_path,
    default_app_path,
    default_log_dir,
    write_agent,
    write_app,
)
from sideband.inputs import Mapping, action_command
from sideband.log import HoldLog
from sideband.protocol import (
    AUDIO_CODEC_UUID,
    AUDIO_DATA_UUID,
    GAP_S,
    OMI_SERVICE_UUID,
    PACKET_HEADER_BYTES,
)


class SidebandApp:
    """Local Mac hold for one Omi pendant. No network."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = home or Path.home()
        self.app_path = default_app_path(self.home)
        self.agent_path = default_agent_path(self.home)
        self.log_dir = default_log_dir(self.home)

    def protocol_lines(self) -> list[str]:
        return [
            f"service {OMI_SERVICE_UUID}",
            f"audio   {AUDIO_DATA_UUID}",
            f"codec   {AUDIO_CODEC_UUID}",
            f"header  {PACKET_HEADER_BYTES} bytes, then one codec frame",
            f"gap     {GAP_S:.1f}s of silence while holding is one drop",
        ]

    async def scan(self, timeout: float = 6.0) -> list[tuple[str, str]]:
        from sideband.radio import scan

        return await scan(timeout)

    async def services(self, address: str) -> list[str]:
        from sideband.radio import services

        return await services(address)

    async def firmware_info(self, address: str) -> list[str]:
        from sideband.radio import firmware_images

        return await firmware_images(address)

    async def firmware_update(self, address: str, package: Path, confirmed: bool) -> int:
        """Dry run unless `confirmed`. Prints the images, then flashes only with the owner's yes."""
        from sideband.firmware import FirmwareError, describe, read_package

        try:
            images = read_package(package)
        except FirmwareError as exc:
            print(f"refusing: {exc}")
            return 1
        print("\n".join(describe(images)))
        if not confirmed:
            print("dry run: nothing sent. Add --yes-flash to install. The bootloader has no rollback.")
            return 0
        from sideband.radio import firmware_flash

        return 0 if await firmware_flash(address, images, print) else 1

    async def hold(
        self,
        address: str,
        log: HoldLog,
        attempts: int = 5,
        seconds: float | None = None,
        wav: Path | None = None,
    ) -> int:
        from sideband.radio import hold

        sink = WavSink(wav) if wav is not None else None
        code = await hold(address, log, attempts=attempts, seconds=seconds, wav=sink)
        if sink is not None:
            log.write(f"wav {sink.path} {sink.seconds():.1f}s frames={sink.frames} bad={sink.bad}")
        return code

    # --- Inputs --------------------------------------------------------------------------------

    @property
    def support_dir(self) -> Path:
        return self.home / "Library" / "Application Support" / "Sideband"

    @property
    def map_path(self) -> Path:
        return self.support_dir / "mappings.json"

    def perform(self, gesture: str, mapping: Mapping) -> str:
        """Start an external action for a gesture. Returns a line for the event log. Never blocks."""
        command = action_command(mapping.action, mapping.arg, gesture)
        if command is None:
            return f"{gesture}: no external action"
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            return f"{gesture}: {mapping.action} failed: {exc}"
        return f"{gesture}: {mapping.action} {mapping.arg}".rstrip()

    @staticmethod
    def keystrokes_allowed() -> bool | None:
        """Whether macOS lets this process (Sideband.app when run through it) send keystrokes. None if unknown."""
        try:
            lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices") or "")
            lib.AXIsProcessTrusted.restype = ctypes.c_bool
            return bool(lib.AXIsProcessTrusted())
        except (OSError, AttributeError):
            return None

    @staticmethod
    def open_accessibility_settings() -> None:
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])

    def run_ui(self, address: str) -> int:
        from sideband.ui import run

        return run(self, address)

    # --- Mac wrapper -------------------------------------------------------------------------

    def build_app(self) -> Path:
        """Write and ad-hoc sign Sideband.app for this venv's python."""
        write_app(self.app_path, Path(sys.executable), __version__)
        subprocess.run(["codesign", "--force", "--sign", "-", str(self.app_path)], check=True, capture_output=True)
        return self.app_path

    def install(self, address: str, wav: Path | None = None) -> list[str]:
        """Build the app, write the login agent, and (re)load it."""
        self.build_app()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        write_agent(self.agent_path, agent_plist(self.app_path, address, self.log_dir, wav))
        self._launchctl("bootout", f"{self._domain()}/{AGENT_LABEL}")
        done = self._launchctl("bootstrap", self._domain(), str(self.agent_path))
        return [
            f"app    {self.app_path}",
            f"agent  {self.agent_path}",
            f"log    {self.log_dir / 'hold.log'}",
            f"launchctl bootstrap: {'ok' if done.returncode == 0 else done.stderr.strip() or done.returncode}",
        ]

    def uninstall(self, remove_app: bool = True) -> list[str]:
        out = self._launchctl("bootout", f"{self._domain()}/{AGENT_LABEL}")
        lines = [f"launchctl bootout: {'ok' if out.returncode == 0 else 'not loaded'}"]
        if self.agent_path.exists():
            self.agent_path.unlink()
            lines.append(f"removed {self.agent_path}")
        if remove_app and self.app_path.exists():
            shutil.rmtree(self.app_path)
            lines.append(f"removed {self.app_path}")
        return lines

    def status(self, tail: int = 5) -> list[str]:
        out = self._launchctl("print", f"{self._domain()}/{AGENT_LABEL}")
        if out.returncode != 0:
            lines = ["agent  not loaded"]
        else:
            fields = dict(
                (key.strip(), value.strip())
                for key, _, value in (line.partition("=") for line in out.stdout.splitlines())
                if value and key.strip() in ("state", "pid", "last exit code", "runs")
            )
            lines = ["agent  " + " ".join(f"{k.replace(' ', '_')}={v}" for k, v in fields.items())]
        lines.append(f"app    {self.app_path if self.app_path.exists() else 'not built'}")
        log = self.log_dir / "hold.log"
        if log.exists():
            lines += log.read_text(encoding="utf-8").splitlines()[-tail:]
        return lines

    def run_via_app(self, argv: list[str]) -> int:
        """Run a sideband command inside Sideband.app so macOS grants Bluetooth to it, streaming output here."""
        if not self.app_path.exists():
            self.build_app()
        with tempfile.TemporaryDirectory(prefix="sideband-") as tmp:
            out, pid_file, exit_file = Path(tmp) / "out", Path(tmp) / "pid", Path(tmp) / "exit"
            out.touch()
            opener = subprocess.Popen(
                [
                    "open", "-W", "-n",
                    "--env", f"SIDEBAND_PIDFILE={pid_file}",
                    "--env", f"SIDEBAND_EXITFILE={exit_file}",
                    "--stdout", str(out), "--stderr", str(out),
                    str(self.app_path), "--args", *argv,
                ]
            )
            with out.open("r", encoding="utf-8", errors="replace") as reader:
                try:
                    while opener.poll() is None:
                        sys.stdout.write(reader.read())
                        sys.stdout.flush()
                        time.sleep(0.2)
                except KeyboardInterrupt:
                    if pid_file.exists():
                        os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
                    opener.wait()
                sys.stdout.write(reader.read())
                sys.stdout.flush()
            if exit_file.exists():
                return int(exit_file.read_text().strip() or 1)
            return 1

    def _domain(self) -> str:
        return f"gui/{os.getuid()}"

    @staticmethod
    def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["launchctl", *args], capture_output=True, text=True)
