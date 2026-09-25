"""Decide when a background hold has dropped. No Bluetooth imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sideband.protocol import GAP_S


class Phase(str, Enum):
    IDLE = "idle"
    HOLDING = "holding"
    GAP = "gap"
    RECOVERING = "recovering"


@dataclass
class Hold:
    phase: Phase = Phase.IDLE
    packets: int = 0
    drops: int = 0
    last_packet_at: float | None = None
    longest_gap_s: float = 0.0


@dataclass(frozen=True)
class Tick:
    state: Hold
    reconnect: bool
    note: str


def _copy(state: Hold, **changes: object) -> Hold:
    data = {
        "phase": state.phase,
        "packets": state.packets,
        "drops": state.drops,
        "last_packet_at": state.last_packet_at,
        "longest_gap_s": state.longest_gap_s,
    }
    data.update(changes)
    return Hold(**data)  # type: ignore[arg-type]


def on_packet(state: Hold, now: float) -> Tick:
    note = "link back" if state.phase in (Phase.GAP, Phase.RECOVERING) else ""
    return Tick(
        _copy(state, phase=Phase.HOLDING, packets=state.packets + 1, last_packet_at=now),
        False,
        note,
    )


def on_clock(state: Hold, now: float) -> Tick:
    """Advance the hold. A reconnect is requested only on the holding → gap edge."""
    if state.phase != Phase.HOLDING or state.last_packet_at is None:
        return Tick(state, False, "")
    gap = now - state.last_packet_at
    longest = max(state.longest_gap_s, gap)
    if gap >= GAP_S:
        return Tick(
            _copy(state, phase=Phase.GAP, drops=state.drops + 1, longest_gap_s=longest),
            True,
            f"gap {gap:.1f}s",
        )
    if longest != state.longest_gap_s:
        return Tick(_copy(state, longest_gap_s=longest), False, "")
    return Tick(state, False, "")


def mark_recovering(state: Hold) -> Hold:
    return _copy(state, phase=Phase.RECOVERING)
