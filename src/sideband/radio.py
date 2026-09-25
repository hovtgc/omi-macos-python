"""bleak session. This is the only module that may import bleak."""

from __future__ import annotations

import asyncio
import signal
import threading
import time
from dataclasses import dataclass
from typing import Callable

from sideband.audio import WavSink
from sideband.firmware import Image
from sideband.log import HoldLog
from sideband.protocol import (
    AUDIO_CODEC_UUID,
    AUDIO_DATA_UUID,
    BATTERY_LEVEL_UUID,
    codec_name,
    strip_packet,
)
from sideband.status import STATUS_S, status_line, summary_line
from sideband.watchdog import Hold, mark_recovering, on_clock, on_packet


SMP_CONNECT_S = 30.0  # service discovery on the pendant can take well over smpclient's default


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


async def services(address: str) -> list[str]:
    """One line per service and characteristic, with properties and a readable value when allowed."""
    from bleak import BleakClient

    lines: list[str] = []
    async with BleakClient(address) as client:
        for service in client.services:
            lines.append(f"service {service.uuid}  {service.description}")
            for char in service.characteristics:
                value = ""
                if "read" in char.properties:
                    try:
                        value = " = " + bytes(await client.read_gatt_char(char.uuid)).hex()
                    except Exception as exc:
                        value = f" = <{exc}>"
                lines.append(f"  char {char.uuid}  [{','.join(char.properties)}]  {char.description}{value}")
    return lines


async def firmware_images(address: str) -> list[str]:
    """Read-only: the MCUboot image slots over SMP (the pendant's firmware update service)."""
    from smpclient import SMPClient
    from smpclient.generics import error, success
    from smpclient.requests.image_management import ImageStatesRead
    from smpclient.transport.ble import SMPBLETransport

    client = SMPClient(SMPBLETransport(), address)
    await client.connect(connect_timeout_s=SMP_CONNECT_S)
    try:
        response = await client.request(ImageStatesRead())
    finally:
        await client.disconnect()
    if error(response) or not success(response):
        return [f"image state read failed: {response}"]
    lines = []
    for image in response.images:
        flags = [name for name in ("active", "confirmed", "pending", "bootable", "permanent") if getattr(image, name, False)]
        digest = bytes(image.hash).hex()[:16] if image.hash else "—"
        lines.append(f"image {image.image or 0} slot {image.slot}  version {image.version}  hash {digest}…  {' '.join(flags)}")
    return lines


async def firmware_flash(address: str, images: list[Image], say: Callable[[str], None]) -> bool:
    """Upload each image over SMP, mark it for install, and reset. The bootloader has no rollback.

    Callers must have the owner's explicit yes before calling this.
    """
    from smpclient import SMPClient
    from smpclient.generics import error, success
    from smpclient.requests.image_management import ImageStatesRead, ImageStatesWrite
    from smpclient.requests.os_management import ResetWrite
    from smpclient.transport.ble import SMPBLETransport

    client = SMPClient(SMPBLETransport(), address)
    await client.connect(connect_timeout_s=SMP_CONNECT_S)
    try:
        for image in images:
            say(f"uploading image {image.index} {image.name} ({image.size} bytes)")
            last = -1
            async for offset in client.upload(image.data, slot=image.index):
                percent = offset * 100 // image.size
                if percent // 10 != last // 10:
                    say(f"  {percent}%")
                    last = percent
        states = await client.request(ImageStatesRead())
        if error(states) or not success(states):
            say(f"image state read failed: {states}")
            return False
        found = {bytes(s.hash) for s in states.images if s.hash}
        for image in images:
            if image.digest not in found:
                say(f"image {image.index} not found on the pendant after upload; not marking it")
                return False
        for image in images:
            done = await client.request(ImageStatesWrite(hash=image.digest, confirm=True))
            if error(done) or not success(done):
                say(f"marking image {image.index} failed: {done}")
                return False
            say(f"image {image.index} marked for install")
        await client.request(ResetWrite())
        say("reset sent; the pendant installs and reboots (can take a minute)")
        return True
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def watch_inputs(
    address: str,
    on_event: Callable[[str, bytes], None],
    stop: asyncio.Event,
    skip: tuple[str, ...] = (AUDIO_DATA_UUID,),
) -> list[str]:
    """Subscribe to every notifying characteristic except `skip`. Calls `on_event(uuid, raw)` until `stop`."""
    from bleak import BleakClient

    watched: list[str] = []
    async with BleakClient(address) as client:
        for uuid in (AUDIO_CODEC_UUID, BATTERY_LEVEL_UUID):
            try:
                on_event(uuid, bytes(await client.read_gatt_char(uuid)))
            except Exception:
                pass
        for service in client.services:
            for char in service.characteristics:
                if "notify" not in char.properties or char.uuid in skip:
                    continue
                uuid = char.uuid
                try:
                    await client.start_notify(uuid, lambda _s, data, uuid=uuid: on_event(uuid, bytes(data)))
                    watched.append(uuid)
                except Exception as exc:
                    on_event(uuid, f"<subscribe failed: {exc}>".encode())
        on_event("", ("watching " + " ".join(watched)).encode())
        while not stop.is_set() and client.is_connected:
            await asyncio.sleep(0.1)
    return watched


async def listen_once(
    address: str,
    state: Hold,
    log: HoldLog,
    stop: asyncio.Event,
    wav: WavSink | None = None,
) -> ListenEnd:
    from bleak import BleakClient

    lock = threading.Lock()

    def on_notify(_sender: object, data: bytearray) -> None:
        nonlocal state
        payload = strip_packet(bytes(data))
        if not payload:
            return
        with lock:
            tick = on_packet(state, time.monotonic())
            state = tick.state
        if tick.note:
            log.write(tick.note)
        if wav is not None:
            wav.feed(payload)

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
        if wav is not None:
            wav.open(log.codec)
        await client.start_notify(AUDIO_DATA_UUID, on_notify)
        battery = "unread" if log.battery is None else f"{log.battery}%"
        log.write(f"notifying {address} codec={log.codec} battery={battery}")
        last_status = time.monotonic()
        last_packets = state.packets
        while not stop.is_set() and client.is_connected:
            now = time.monotonic()
            with lock:
                tick = on_clock(state, now)
                state = tick.state
            if tick.reconnect:
                log.write(tick.note)
                return ListenEnd(state, "gap")
            if now - last_status >= STATUS_S:
                line = status_line(state, last_packets, now - last_status, log.battery)
                if wav is not None:
                    line += f" wav={wav.seconds():.0f}s"
                log.write(line)
                last_status, last_packets = now, state.packets
            await asyncio.sleep(0.25)
        if stop.is_set():
            return ListenEnd(state, "stop")
        return ListenEnd(state, "lost")


async def hold(
    address: str,
    log: HoldLog,
    attempts: int = 5,
    seconds: float | None = None,
    wav: WavSink | None = None,
) -> int:
    """Hold until stopped. `attempts` is the budget of reopens in a row with no frames between them."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    if seconds is not None:
        loop.call_later(seconds, stop.set)

    state = Hold()
    failures = 0
    try:
        while True:
            if stop.is_set():
                log.write("stopped")
                return 0
            before = state.packets
            try:
                ended = await listen_once(address, state, log, stop, wav)
            except Exception as exc:
                log.write(f"radio error: {exc}")
                ended = ListenEnd(mark_recovering(state), "lost")
            state = ended.state
            if ended.reason == "stop":
                log.write(summary_line(state, log.battery))
                log.write("stopped")
                return 0
            if ended.reason == "gap":
                state = mark_recovering(state)
            failures = 0 if state.packets > before else failures + 1
            if failures >= attempts:
                log.write("gave up")
                return 1
            log.write(f"reopen {failures + 1}/{attempts} ({ended.reason})")
            try:
                await asyncio.wait_for(stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
    finally:
        if wav is not None:
            wav.close()
