# Tasks

Do the first unchecked item only. Leave `sh scripts/test.sh` green. Stop.

- [x] On a Mac, next to a pendant: run `sideband scan`. If a device named Omi appears, append its name and address to `NOTES.md`. If none appears, append the error and stop. Do not invent an address.
- [ ] Run `sideband hold --address <that id>` and hide the terminal for 30 seconds. Append whether frames kept arriving or a gap was logged. Do not change `GAP_S` to force a pass. (35 s through Sideband.app held with no gap; a later run logged one real gap whose reopen was not observed. Repeat for 5 minutes and confirm the reopen.)
- [ ] Run `sideband install --address <id>`, quit every terminal, log out and back in. Confirm with `sideband status` that the agent is running and frames are arriving. Note the result in `NOTES.md`.
- [x] Add optional WAV capture (`sideband hold --wav session.wav`) behind an `audio` extra. Decode only after `strip_packet`. No network transcription.
- [x] Build stock firmware with nRF Connect SDK 2.9.0 for `omi/nrf5340/cpuapp` and confirm the build is reproducible before changing anything.
- [x] Apply `firmware/accel-stream.patch`, build, and review the diff. Do not flash without the owner's explicit yes.
- [x] Rehearse OTA with the official `Omi_CV1_OTA_v3.0.21.zip` over SMP from the Mac, then flash the motion build. Confirm `32403791` notifies 12 bytes at about 50 Hz and that tilt steers Omi Flap 3D.
- [ ] Play Omi Voice Flap on the pendant mic for 2 minutes. Note how many spoken commands were missed or misheard and the typical delay. Do not widen the grammar to force a pass.
