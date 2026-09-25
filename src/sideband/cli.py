"""Entry point for the Python app. `protocol` needs no Bluetooth. `scan` and `hold` do."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sideband.app import SidebandApp
from sideband.log import HoldLog


def _scan(app: SidebandApp, timeout: float) -> int:
    try:
        rows = asyncio.run(app.scan(timeout))
    except Exception as exc:
        print(f"scan failed: {exc}", file=sys.stderr)
        print("On a Mac: System Settings → Privacy & Security → Bluetooth, allow this terminal.", file=sys.stderr)
        return 1
    if not rows:
        print("No device named Omi. Wake the pendant and stay next to the Mac.")
        return 2
    for name, address in rows:
        print(f"{name}  {address}")
    return 0


def _hold(app: SidebandApp, address: str, log_path: Path | None, attempts: int) -> int:
    log = HoldLog(log_path)
    try:
        return asyncio.run(app.hold(address, log, attempts=attempts))
    except Exception as exc:
        log.write(f"hold failed: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sideband", description="Python app that holds an Omi pendant on Bluetooth.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("protocol", help="Print the wire contract.")

    scan = sub.add_parser("scan", help="List nearby devices named Omi.")
    scan.add_argument("--timeout", type=float, default=6.0)

    hold = sub.add_parser("hold", help="Keep notifications open and reconnect after a gap.")
    hold.add_argument("--address", required=True)
    hold.add_argument("--log", type=Path, default=None, help="Append the same lines to a file.")
    hold.add_argument("--attempts", type=int, default=5)

    args = parser.parse_args(argv)
    app = SidebandApp()
    if args.cmd == "protocol":
        print("\n".join(app.protocol_lines()))
        return 0
    if args.cmd == "scan":
        return _scan(app, args.timeout)
    return _hold(app, args.address, args.log, args.attempts)
