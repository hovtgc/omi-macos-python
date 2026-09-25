"""bleak session. This is the only module that may import bleak."""

from __future__ import annotations

import asyncio
import signal
import threading
import time
from dataclasses import dataclass

from sideband.log import HoldLog
from sideband.protocol import (
    AUDIO_CODEC_UUID,
    AUDIO_DATA_UUID,
    BATTERY_LEVEL_UUID,
    codec_name,
    strip_packet,
)
from sideband.watchdog import Hold, mark_recovering, on_clock, on_packet


@dataclass
class ListenEnd:
    state: Hold
    reason: str


async def scan(timeout: float = 6.0) -> list[tuple[str, str]]:
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=timeout)
    rows: list[tuple[str, str]] = []
    for device in found:
        name = device.name or ""
        if "omi" in name.lower():
            rows.append((name, device.address))
    return rows


async def listen_once(address: str, state: Hold, log: HoldLog, stop: asyncio.Event) -> ListenEnd:
    from bleak import BleakClient

    lock = threading.Lock()

    def on_notify(_sender: object, data: bytearray) -> None:
        nonlocal state
        if not strip_packet(bytes(data)):
            return
        with lock:
            state = on_packet(state, time.monotonic()).state

    async with BleakClient(address) as client:
        try:
            raw = await client.read_gatt_char(AUDIO_CODEC_UUID)
            log.codec = codec_name(raw[0]) if raw else "unread"
        except Exception:
            log.codec = "unread"
        try:
            level = await client.read_gatt_char(BATTERY_LEVEL_UUID)
            log.battery = level[0] if level else None
        except Exception:
            log.battery = None
        await client.start_notify(AUDIO_DATA_UUID, on_notify)
        battery = "unread" if log.battery is None else f"{log.battery}%"
        log.write(f"notifying {address} codec={log.codec} battery={battery}")
        while not stop.is_set() and client.is_connected:
            with lock:
                tick = on_clock(state, time.monotonic())
                state = tick.state
            if tick.reconnect:
                log.write(tick.note)
                return ListenEnd(state, "gap")
            await asyncio.sleep(0.25)
        if stop.is_set():
            return ListenEnd(state, "stop")
        return ListenEnd(state, "lost")


async def hold(address: str, log: HoldLog, attempts: int = 5) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    state = Hold()
    for attempt in range(1, attempts + 1):
        if stop.is_set():
            log.write("stopped")
            return 0
        try:
            ended = await listen_once(address, state, log, stop)
        except Exception as exc:
            log.write(f"radio error: {exc}")
            ended = ListenEnd(mark_recovering(state), "lost")
        state = ended.state
        if ended.reason == "stop":
            log.write("stopped")
            return 0
        if ended.reason == "gap":
            state = mark_recovering(state)
        log.write(f"reopen {attempt}/{attempts}")
        await asyncio.sleep(1.0)
    log.write("gave up")
    return 1
