"""Entry point for the Python app. `protocol` needs no Bluetooth. `scan` and `hold` do."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sideband.app import SidebandApp
from sideband.log import HoldLog

RADIO_COMMANDS = ("scan", "hold", "services", "ui", "firmware")


def _scan(app: SidebandApp, timeout: float) -> int:
    try:
        rows = asyncio.run(app.scan(timeout))
    except Exception as exc:
        print(f"scan failed: {exc}", file=sys.stderr)
        print("On a Mac: System Settings → Privacy & Security → Bluetooth, allow Sideband.", file=sys.stderr)
        return 1
    if not rows:
        print("No device named Omi. Wake the pendant and stay next to the Mac.")
        return 2
    for name, address in rows:
        print(f"{name}  {address}")
    return 0


def _hold(app: SidebandApp, args: argparse.Namespace) -> int:
    log = HoldLog(args.log)
    try:
        return asyncio.run(app.hold(args.address, log, attempts=args.attempts, seconds=args.seconds, wav=args.wav))
    except Exception as exc:
        log.write(f"hold failed: {exc}")
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sideband", description="Python app that holds an Omi pendant on Bluetooth.")
    parser.add_argument(
        "--via-app",
        action="store_true",
        default=os.environ.get("SIDEBAND_VIA_APP") == "1",
        help="Run scan/hold inside Sideband.app. Use from shells macOS will not grant Bluetooth (agents, IDEs).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("protocol", help="Print the wire contract.")

    scan = sub.add_parser("scan", help="List nearby devices named Omi.")
    scan.add_argument("--timeout", type=float, default=6.0)

    services = sub.add_parser("services", help="List the pendant's GATT services and characteristics.")
    services.add_argument("--address", required=True)

    firmware = sub.add_parser("firmware", help="Show firmware image slots, or install an OTA zip.")
    firmware.add_argument("--address", required=True)
    firmware.add_argument("--update", type=Path, default=None, help="OTA zip. A dry run unless --yes-flash is given.")
    firmware.add_argument("--yes-flash", action="store_true", help="Really install. The bootloader has no rollback.")

    ui = sub.add_parser("ui", help="Open the input explorer: live button, mic, and state, with gesture mapping.")
    ui.add_argument("--address", default=None, help="Default: the first Omi found by a scan.")

    hold = sub.add_parser("hold", help="Keep notifications open and reconnect after a gap.")
    hold.add_argument("--address", required=True)
    hold.add_argument("--log", type=Path, default=None, help="Append the same lines to a file.")
    hold.add_argument("--attempts", type=int, default=5, help="Reopens in a row with no frames before giving up.")
    hold.add_argument("--seconds", type=float, default=None, help="Stop after this long. Default: run until stopped.")
    hold.add_argument("--wav", type=Path, default=None, help="Also decode audio to this WAV file. Needs the audio extra.")

    install = sub.add_parser("install", help="Build Sideband.app and load it as a login agent.")
    install.add_argument("--address", required=True)
    install.add_argument("--wav", type=Path, default=None, help="Record every session to this WAV file.")

    uninstall = sub.add_parser("uninstall", help="Unload the login agent and remove Sideband.app.")
    uninstall.add_argument("--keep-app", action="store_true")

    sub.add_parser("status", help="Show the login agent and the last log lines.")
    sub.add_parser("build-app", help="Write and sign Sideband.app without loading an agent.")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(raw)
    app = SidebandApp()
    if args.via_app and args.cmd in RADIO_COMMANDS:
        return app.run_via_app([a for a in raw if a != "--via-app"])
    if args.cmd == "protocol":
        print("\n".join(app.protocol_lines()))
        return 0
    if args.cmd == "scan":
        return _scan(app, args.timeout)
    if args.cmd == "hold":
        return _hold(app, args)
    if args.cmd == "ui":
        return app.run_ui(args.address)
    if args.cmd == "firmware":
        if args.update is not None:
            return asyncio.run(app.firmware_update(args.address, args.update, args.yes_flash))
        print("\n".join(asyncio.run(app.firmware_info(args.address))))
        return 0
    if args.cmd == "services":
        print("\n".join(asyncio.run(app.services(args.address))))
        return 0
    if args.cmd == "install":
        lines = app.install(args.address, args.wav)
    elif args.cmd == "uninstall":
        lines = app.uninstall(remove_app=not args.keep_app)
    elif args.cmd == "build-app":
        lines = [str(app.build_app())]
    else:
        lines = app.status()
    print("\n".join(lines))
    return 0
