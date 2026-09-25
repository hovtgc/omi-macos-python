# Sideband

This is a Python application for a Mac. Keep it Python. Do not port it to Swift, JavaScript, or a web UI.

Work only in this directory. The parent folder is not part of the project.

Follow `AGENTS.md` here. It is the contract for Codex and Claude Code.

Non-negotiable, even if you skip the rest:

- Extend `SidebandApp` in `src/sideband/app.py`. `cli.py` only parses arguments.
- The gap rule is only in `src/sideband/watchdog.py` (`GAP_S` = 2 seconds, one drop per silence).
- `radio.py` is the only file that may import `bleak`.
- Run `sh scripts/test.sh` and leave it green. Tests must pass without a pendant.
- Do the first unchecked item in `TASKS.md`, then stop.
