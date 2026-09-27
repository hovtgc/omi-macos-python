# Sideband

A Python Mac app for the Omi pendant. Keep it Python. Do not port it to Swift, JavaScript, or a web UI.

Work only in this directory. The parent folder is not part of the project.

Follow `AGENTS.md` here. It is the contract for Codex and Claude Code.

**If the user wants to set up or use Sideband, follow `ONBOARDING.md` step by step** (start with `sh scripts/setup.sh`). Do not work on `TASKS.md` for them.

Non-negotiable, even if you skip the rest:

- Radio commands go through the app: `sideband --via-app …` or `sideband open …`. Bare Bluetooth from your shell is killed by macOS.
- Never flash firmware without the user's explicit yes in chat, asked again before each flash.
- Extend `SidebandApp` in `src/sideband/app.py`. `cli.py` only parses arguments.
- The gap rule is only in `src/sideband/watchdog.py` (`GAP_S` = 2 seconds, one drop per silence).
- `radio.py` is the only file that may import `bleak` or `smpclient`.
- Run `sh scripts/test.sh` and leave it green. Tests must pass without a pendant.
- When changing code (not setting up), do the first unchecked item in `TASKS.md`, then stop.
