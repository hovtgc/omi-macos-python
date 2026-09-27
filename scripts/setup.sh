#!/bin/sh
# One-command setup for Sideband. Safe to run again: it only does what is missing.
#   sh scripts/setup.sh              everything, including ~6 GB of models
#   sh scripts/setup.sh --no-models  skip the model downloads (transcriber and assistant fetch them on first use)
set -eu
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
MODELS=1
[ "${1:-}" = "--no-models" ] && MODELS=0

say() { printf '\n==> %s\n' "$1"; }

say "Checking this Mac"
if [ "$(uname -s)" != "Darwin" ]; then echo "Sideband is a macOS app."; exit 1; fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "Note: this is an Intel Mac. Bluetooth, Controls and the Arcade work; the transcriber and assistant need Apple silicon."
fi

say "Getting uv (fetches a modern Python; macOS ships 3.9)"
UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  python3 -m pip install --user --quiet uv
  UV="$(python3 -m site --user-base)/bin/uv"
fi
"$UV" --version

say "Creating .venv with Python 3.12"
[ -x .venv/bin/python ] || "$UV" venv --quiet --python 3.12 .venv
EXTRAS="audio,firmware,voice"
[ "$(uname -m)" = "arm64" ] && EXTRAS="$EXTRAS,transcribe,llm"
"$UV" pip install --quiet --python .venv/bin/python -e ".[${EXTRAS}]"
.venv/bin/python --version

say "Running the tests (no pendant needed)"
PATH="$ROOT/.venv/bin:$PATH" sh scripts/test.sh >/tmp/sideband-tests.log 2>&1 && tail -n 1 /tmp/sideband-tests.log || {
  tail -n 30 /tmp/sideband-tests.log; echo "Tests failed; see /tmp/sideband-tests.log"; exit 1; }

say "Building ~/Applications/Sideband.app (it holds the Bluetooth permission)"
.venv/bin/sideband build-app

if [ "$MODELS" = 1 ]; then
  say "Downloading local models (Whisper ~1.6 GB, assistant ~4.3 GB, voice ~40 MB; skipped if present)"
  .venv/bin/sideband models --download
fi

say "Doctor"
.venv/bin/sideband doctor || true

cat <<EOF

Done. Next, on your side (an agent cannot do these for you):
  1. Wake the Omi pendant (tap it) and keep it near the Mac.
  2. Start Sideband:  $ROOT/.venv/bin/sideband open launcher
     (or double-click ~/Applications/Sideband.app, or Spotlight "Sideband")
  3. When macOS asks, allow Bluetooth for "Sideband".
Then follow ONBOARDING.md from step 4.
EOF
