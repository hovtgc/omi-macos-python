"""One-line hold summaries for the log. No Bluetooth imports."""

from __future__ import annotations

from sideband.watchdog import Hold

STATUS_S = 10.0


def _power(battery: int | None) -> str:
    return "unread" if battery is None else f"{battery}%"


def status_line(state: Hold, prev_packets: int, span_s: float, battery: int | None) -> str:
    """Summarize the hold since the previous line, `span_s` seconds ago."""
    new = state.packets - prev_packets
    rate = new / span_s if span_s > 0 else 0.0
    return (
        f"{state.phase.value} frames={state.packets} (+{new}, {rate:.1f}/s) "
        f"drops={state.drops} longest_gap={state.longest_gap_s:.1f}s battery={_power(battery)}"
    )


def summary_line(state: Hold, battery: int | None) -> str:
    """Totals for the whole run."""
    return (
        f"total frames={state.packets} drops={state.drops} "
        f"longest_gap={state.longest_gap_s:.1f}s battery={_power(battery)}"
    )
