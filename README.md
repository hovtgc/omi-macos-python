# Omi — macOS Python app

v0.1. Holds an Omi pendant on Bluetooth from a Mac, including after the terminal is in the background.

The Python package is `sideband`. Open this folder in Codex or Claude Code, read `AGENTS.md` (Claude Code also reads `CLAUDE.md`), and do the first unchecked item in `TASKS.md`. Stay in Python.

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
sh scripts/test.sh
.venv/bin/sideband scan
.venv/bin/sideband hold --address <id>
```

The pendant must be awake and next to the Mac. macOS will ask for Bluetooth permission.

This is not the Omi phone app, and it does not send audio anywhere. MIT licensed.
