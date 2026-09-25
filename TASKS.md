# Tasks

Do the first unchecked item only. Leave `sh scripts/test.sh` green. Stop.

- [ ] On a Mac, next to a pendant: run `sideband scan`. If a device named Omi appears, append its name and address to `NOTES.md`. If none appears, append the error and stop. Do not invent an address.
- [ ] Run `sideband hold --address <that id>` and hide the terminal for 30 seconds. Append whether frames kept arriving or a gap was logged. Do not change `GAP_S` to force a pass.
- [ ] Copy `launchd/com.sideband.hold.plist` into `~/Library/LaunchAgents/`, replace the two placeholders, and load it. Confirm the process is alive after the terminal quits. Note the `launchctl` result in `NOTES.md`.
- [ ] Add optional WAV capture (`sideband hold --wav session.wav`) behind an `audio` extra. Decode only after `strip_packet`. No network transcription.
