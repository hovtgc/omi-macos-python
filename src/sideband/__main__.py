import os

from sideband.cli import main

if __name__ == "__main__":
    code = main()
    exit_file = os.environ.get("SIDEBAND_EXITFILE")
    if exit_file:
        with open(exit_file, "w", encoding="utf-8") as handle:
            handle.write(str(code))
    raise SystemExit(code)
