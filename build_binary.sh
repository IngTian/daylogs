#!/usr/bin/env bash
# Build a standalone `day` binary with PyInstaller.
#
# Produces dist/day — a single file with Python and textual inside, runnable on
# any Mac of the same architecture with no Python installed. It does NOT bundle
# the `claude` CLI: calorie estimation and the daily summary still shell out to
# it, and everything else works without it.
#
# MEASURED CAVEAT — read before using this daily. --onefile unpacks the whole
# 15 MB archive to a temp dir on every launch: startup is ~4,770 ms versus
# ~60 ms for a console-script shim on PATH. For a tool you open several times a
# day that is the wrong trade. This exists for handing the app to a machine
# with no Python. For your own machine, symlink the console script instead:
#
#     ln -sf "$(command -v day)" ~/.local/bin/day
#
# Swap --onefile for --onedir below if you want a fast-starting bundle and can
# live with a folder instead of a single file.
#
# PyInstaller is a build-only tool and is deliberately not a project
# dependency; install it ad hoc:  pip install pyinstaller
set -euo pipefail

cd "$(dirname "$0")"

pyinstaller \
  --name day \
  --onefile \
  --console \
  --clean \
  --noconfirm \
  --collect-all textual \
  --collect-submodules daylogs \
  --add-data "daylogs/tui/app.tcss:daylogs/tui" \
  --exclude-module pytest \
  --exclude-module _pytest \
  --exclude-module ruff \
  entry.py

echo
echo "built: $(pwd)/dist/day"
ls -lh dist/day
