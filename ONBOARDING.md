# Onboarding: from clone to transcribing

This is the setup playbook. If you are an agent (Claude Code, Codex, …) and the user wants to set up or use Sideband, follow it top to bottom: run each step, check the result, and stop at 🧑 steps until the user says they are done. Tell the user what you are doing in plain words. If a check fails, use the "If it fails" note before moving on.

🧑 marks steps only the human can do: macOS permission prompts, waking or tapping the pendant, and saying yes to a firmware flash. An agent cannot click "Allow" for them.

**What you need:** an Omi pendant (Omi CV 1 for the optional motion firmware), and a Mac. The transcriber and assistant need Apple silicon (M1 or later) on macOS 13+. About 8 GB free disk for the models.

---

## 1. Install (agent)

```sh
sh scripts/setup.sh
```

This installs `uv` if needed, makes `.venv` with Python 3.12, installs every extra, runs the tests, builds `~/Applications/Sideband.app`, downloads the local models (Whisper, the Qwen2.5-7B assistant, the Vosk voice model: about 6 GB), and runs `sideband doctor`. It is safe to run again.

- **Check:** the last `doctor` block ends with `All required checks pass.` (✓ everywhere except the pendant lines, which come later).
- **If it fails:** read the `→` line under each ✗. On a slow connection use `sh scripts/setup.sh --no-models`; the models then download on first use.

## 2. 🧑 Wake the pendant

Ask the user to tap the Omi once and keep it within a metre or two of the Mac. If they have the Omi phone app open, close it so the pendant is free.

Do not ask them to hold the button: **holding it for 3 seconds turns the pendant off.**

## 3. Start Sideband and allow Bluetooth

```sh
.venv/bin/sideband open launcher
```

🧑 macOS shows "Sideband would like to use Bluetooth". The user clicks **Allow**. This happens once.

- **Check:** the launcher window's top right says `connected` with a battery level within about 10 s. If there is no remembered pendant yet, it scans and connects to the first Omi it finds.
- **If it fails:** open the Bluetooth app (⌘4) and use Scan. See the troubleshooting table below.

Why an app: macOS gives Bluetooth only to the app that started a process. Python run straight from an agent or an IDE is killed silently with SIGABRT. Always run radio commands as `sideband --via-app …` or through `sideband open …`; never run `sideband scan` bare from an agent shell.

## 4. Check the pendant

With the launcher open, the Bluetooth app shows the device, status, battery, audio stream and motion. From a shell, while the launcher is **not** running:

```sh
.venv/bin/sideband --via-app doctor --pendant
```

- **Check:** a `Pendant` block with the model, firmware and battery. `features` lists what the firmware offers. `motion: not in this firmware` is normal for stock firmware; everything except the tilt games works without it.

## 5. First transcript

1. Open the Transcriber: ⌘1 in the launcher, or `.venv/bin/sideband open transcriber`.
2. 🧑 The user clicks the big red button (or double taps the Omi if double is mapped to *record*), says a few sentences, and stops.
3. It transcribes on the Mac in a few seconds, **speaks a short callout** of what was said (a local model writes it for the ear; the Mac's voice reads it), then adds a written summary and action items. 🔊 Speak replays it; both are switches under the transcript.
4. 🧑 The user asks a question in the box under the transcript, e.g. "what did I say about …?", or switches the scope to "all recordings".

- **Check:** the recording shows `ready` and the reading pane has timestamped lines and a `## Summary` block.
- **If it fails:** an empty transcript usually means the audio stream stopped (Bluetooth app → "Audio stream"; reconnect). A missing model shows in `sideband doctor`.

Privacy: audio and transcripts stay on this Mac, in `~/Library/Application Support/Sideband/recordings/`. Recording audio deletes itself after 24 hours; transcripts are kept. "Transcribe a file…" handles any audio or video file (Voice Memos, m4a, mp3, …).

## 6. Taps, voice and the Arcade

- **Controls (⌘2):** map single / double / triple / hold taps to Mac actions (open an app, keystroke, Shortcut, URL, volume, record, voice menu, …). Mappings work with every window closed.
  - 🧑 Keystroke actions need **System Settings → Privacy & Security → Accessibility → Sideband** switched on. The Controls window has a button that opens that page.
- **Voice menu:** press ⌘L (or map a tap to *voice menu*) and speak into the pendant: "open arcade", "start recording", "summarize that", "play marble", "close".
- **Arcade (⌘3):** played with the pendant alone. It calibrates motion as soon as it opens (🧑 hold still, then tilt right, then tilt forward; later only "hold still"). Tilt moves the pointer, **double tap** plays or goes forward, **single tap** goes back, a **hold** pauses or recalibrates. Without motion (stock firmware) single taps cycle the games. Sky Ace 1943, Corn Maze, Star Dodger and Omi Catch steer by tilt and need motion (step 7); Omi Flap 3D and Voice Flap work on stock firmware.
  - 🧑 **A hold means about one second, then let go.** Holding the button for 3 seconds turns the pendant off, and the pendant only reports a hold when released, so nothing can warn mid-press.

## 7. Optional: motion firmware for tilt games (Omi CV 1 only)

Skip this unless the user wants tilt and shake. Stock firmware compiles the pendant's 6-axis sensor out. The Sideband motion build is Omi's 3.0.21 plus [`firmware/accel-stream.patch`](firmware/accel-stream.patch), which streams it at about 50 Hz.

**Tell the user the risk before anything else, in these words:** the pendant's bootloader has no rollback. A firmware that failed to boot could only be recovered with a hardware debug probe. This build has been run on one Omi CV 1 (hardware 5.0); Omi's official images are signed with the same public key, so the pendant accepts it. **Only continue if the user types a clear yes, and ask again before each flash.**

Quit the launcher first (the flasher needs the pendant free), keep the pendant charged and next to the Mac, and do not press its button during an update.

```sh
# a. Dry run: download, verify the pinned SHA-256, show what would be installed. Nothing is sent.
.venv/bin/sideband firmware --install official
.venv/bin/sideband firmware --install motion

# b. 🧑 After an explicit yes: rehearse with Omi's official 3.0.21 (a normal update; proves the path).
.venv/bin/sideband --via-app firmware --install official --yes-flash

# c. 🧑 After a second explicit yes: the motion build.
.venv/bin/sideband --via-app firmware --install motion --yes-flash

# d. Check: motion listed in features, "tilt games work".
.venv/bin/sideband --via-app doctor --pendant
```

These use the pendant Sideband remembers; add `--address <id>` for another one.

The flasher refuses a file whose checksum differs from the pinned one, and refuses any pendant that does not report `Omi CV 1`. It reboots the pendant when done (10–30 s). To go back to stock at any time, run step b again. To build the motion firmware yourself instead of using the release, see [firmware/README.md](firmware/README.md).

Tilt then works holding the Omi in your hand, flat or upright. Wherever it is when a game starts counts as centre. For unusual grips, Arcade → **Calibrate tilt** takes three steps.

## 8. Optional: keep the link alive at login

```sh
.venv/bin/sideband install --address <id from the Bluetooth app>   # a login agent; audio is only counted, not recorded
.venv/bin/sideband status
```

Use this *or* the launcher, not both at once: one process holds the pendant.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Command exits with code 134 and no output | Bluetooth permission crash: run it through the app (`--via-app` / `sideband open`). |
| Launcher stuck on `connecting` | Tap the pendant to wake it; Bluetooth app → Reconnect now. |
| Scan finds no Omi | It is asleep, off (after a 3 s hold), connected to a phone, or already connected to Sideband (a connected pendant does not advertise). |
| `stream 0 frames/s` while connected | The pendant paused audio; Bluetooth app → Reconnect now. |
| Keystrokes do nothing | Accessibility → Sideband on; the first keystroke also asks for "System Events" control. |
| Moved the project folder | `sideband build-app`, then allow Bluetooth / Accessibility again. |
| Tilt goes the wrong way | Arcade → Calibrate tilt, or Recentre. |

Useful commands: `sideband doctor`, `sideband open <launcher|transcriber|controls|arcade|bluetooth>`, `sideband models --download`, `sideband --help`.
