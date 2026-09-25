"""The Mac wrapper around the Python app. Pure builders, plus writers that touch only the paths given.

macOS charges Bluetooth to the app that started a process. A bare python, or python under a host
without NSBluetoothAlwaysUsageDescription, is killed by TCC with SIGABRT before bleak can raise.
`Sideband.app` is a signed-ad-hoc bundle that carries the usage string and execs this venv's python,
so the grant belongs to Sideband and survives terminals, agents, and launchd.
"""

from __future__ import annotations

import plistlib
import shlex
from pathlib import Path

APP_NAME = "Sideband"
BUNDLE_ID = "com.sideband.app"
AGENT_LABEL = "com.sideband.hold"
BLUETOOTH_REASON = "Sideband keeps your Omi pendant connected over Bluetooth. Audio stays on this Mac."


def default_app_path(home: Path) -> Path:
    return home / "Applications" / f"{APP_NAME}.app"


def default_agent_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"


def default_log_dir(home: Path) -> Path:
    return home / "Library" / "Logs" / "sideband"


def info_plist(version: str) -> dict:
    return {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSUIElement": True,
        "LSMinimumSystemVersion": "12.0",
        "NSBluetoothAlwaysUsageDescription": BLUETOOTH_REASON,
    }


def launcher_script(python: Path) -> str:
    """Exec keeps the pid, so the process stays Sideband's for TCC. The pid file lets `--via-app` stop it."""
    return (
        "#!/bin/sh\n"
        'if [ -n "${SIDEBAND_PIDFILE:-}" ]; then echo $$ > "$SIDEBAND_PIDFILE"; fi\n'
        f'exec {shlex.quote(str(python))} -m sideband "$@"\n'
    )


def agent_plist(app: Path, address: str, log_dir: Path, wav: Path | None = None) -> dict:
    args = [str(app / "Contents" / "MacOS" / APP_NAME), "hold", "--address", address, "--log", str(log_dir / "hold.log")]
    if wav is not None:
        args += ["--wav", str(wav)]
    return {
        "Label": AGENT_LABEL,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "launchd.out.log"),
        "StandardErrorPath": str(log_dir / "launchd.err.log"),
    }


def write_app(app: Path, python: Path, version: str) -> Path:
    """Write the bundle. Returns the launcher path. The caller signs it."""
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    with (app / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(info_plist(version), handle)
    launcher = macos / APP_NAME
    launcher.write_text(launcher_script(python), encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def write_agent(path: Path, plist: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(plist, handle)
