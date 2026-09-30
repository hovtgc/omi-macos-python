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

    async def pendant_facts(self, address: str) -> dict[str, bytes]:
        from sideband.radio import pendant_facts

        return await pendant_facts(address)

    def saved_address(self) -> str | None:
        import json

        try:
            return json.loads((self.support_dir / "device.json").read_text(encoding="utf-8")).get("address") or None
        except (OSError, ValueError):
            return None

    def download_models(self) -> list[str]:
        """Fetch Whisper, the assistant model and the Vosk voice model, skipping what is already here."""
        import urllib.request
        import zipfile

        from sideband.llm import MODEL as LLM_MODEL
        from sideband.transcribe import MODEL as WHISPER_MODEL
        from sideband.voice import MODEL_URL, model_path

        done = []
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            return ["missing huggingface_hub: pip install -e '.[transcribe,llm]'"]
        for name in (WHISPER_MODEL, LLM_MODEL):
            print(f"model {name}", flush=True)
            snapshot_download(name)
            done.append(f"✓ {name}")
        vosk_dir = model_path(self.support_dir)
        if not vosk_dir.is_dir():
            print(f"model {vosk_dir.name}", flush=True)
            vosk_dir.parent.mkdir(parents=True, exist_ok=True)
            archive = vosk_dir.parent / "vosk.zip"
            urllib.request.urlretrieve(MODEL_URL, archive)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(vosk_dir.parent)
            archive.unlink()
        done.append(f"✓ {vosk_dir.name}")
        return done

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
        facts = await self.pendant_facts(address)
        model = facts.get("model", b"").decode("utf-8", "replace").strip("\x00")
        if model != "Omi CV 1":
            print(f"refusing: this firmware is for the Omi CV 1, and the pendant says {model or 'nothing'!r}")
            return 1
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

    @property
    def recordings_dir(self) -> Path:
        return self.support_dir / "recordings"

    def sweep_recordings(self, keep: set[Path] | None = None) -> list[Path]:
        """Delete recording audio older than 24 hours. Transcripts are kept."""
        from sideband.recordings import sweep

        return sweep(self.recordings_dir, time.time(), keep=keep)

    # --- Assistant API key ---------------------------------------------------------------------

    KEYCHAIN_SERVICE = "Sideband assistant API key"

    def api_key(self) -> str:
        """The key for a hosted assistant API: the login Keychain, else $SIDEBAND_API_KEY."""
        try:
            found = subprocess.run(
                ["security", "find-generic-password", "-s", self.KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if found.returncode == 0 and found.stdout.strip():
                return found.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return os.environ.get("SIDEBAND_API_KEY", "")

    def set_api_key(self, key: str) -> None:
        """Keep the key in the login Keychain (never in settings.json). An empty key removes it."""
        subprocess.run(["security", "delete-generic-password", "-s", self.KEYCHAIN_SERVICE], capture_output=True)
        if key:
            subprocess.run(
                ["security", "add-generic-password", "-U", "-s", self.KEYCHAIN_SERVICE, "-a", "sideband", "-w", key],
                capture_output=True, check=True,
            )

    @staticmethod
    def add_reminder(name: str, notes: str) -> str:
        """Add a reminder to the default list in Apple Reminders. Returns '' or the error."""

        def quoted(text: str) -> str:
            return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

        script = f"tell application \"Reminders\" to make new reminder with properties {{name:{quoted(name)}, body:{quoted(notes)}}}"
        try:
            done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            return str(exc)
        return "" if done.returncode == 0 else (done.stderr.strip() or "Reminders refused")

    @staticmethod
    def open_path(path: Path, reveal: bool = False) -> None:
        """Open a file in its default app, or reveal it in Finder."""
        subprocess.Popen(["open", "-R", str(path)] if reveal else ["open", str(path)])

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

    @property
    def launcher_pid_path(self) -> Path:
        return self.support_dir / "launcher.pid"

    @property
    def open_request_path(self) -> Path:
        return self.support_dir / "open-request"

    def launcher_running(self) -> bool:
        try:
            os.kill(int(self.launcher_pid_path.read_text(encoding="utf-8")), 0)
            return True
        except (OSError, ValueError):
            return False

    def open_app(self, name: str) -> str:
        """Bring up one Sideband app. Reuses a running launcher; otherwise starts Sideband.app."""
        if self.launcher_running():
            self.open_request_path.write_text(name, encoding="utf-8")
            return f"asked the running launcher to open {name}"
        if not self.app_path.exists():
            self.build_app()
        args = ["ui"] + ([] if name == "launcher" else ["--open", name])
        subprocess.Popen(["open", "-n", str(self.app_path), "--args", *args])
        return f"started Sideband with {name}"

    def run_ui(self, address: str | None, open_app: str | None = None) -> int:
        from sideband.ui import run

        return run(self, address, open_app)

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
