"""The Python application. The command line and launchd both call this object."""

from __future__ import annotations

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

    async def hold(self, address: str, log: HoldLog, attempts: int = 5) -> int:
        from sideband.radio import hold

        return await hold(address, log, attempts=attempts)
