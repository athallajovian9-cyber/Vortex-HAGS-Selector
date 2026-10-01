#!/usr/bin/env bash
# Build Vortex_HAGS_Selector.exe (Nuitka onefile).
#
# Two things decide whether this works, and neither is obvious:
#
#   1. WHICH PYTHON. Nuitka's tk-inter plugin needs a Tcl directory on disk. The
#      pythoncore 3.14 install used for day-to-day work reports
#      //zipfs:/lib/tcl/tcl_library - Tcl lives inside a zip there, so the plugin
#      always fails with "Could not find Tcl". The 3.11 runtime bundles
#      tcl/tcl8.6 on disk and builds. Probe, never assume.
#
#   2. THE TCL PATH IS THE VERSIONED DIR. --tcl-library-dir must be <root>/tcl/tcl8.6,
#      not <root>/tcl. Wrong value builds fine and dies at startup with
#      "Can't find a usable init.tcl".
#
# Usage:  bash build.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && { pwd -W 2>/dev/null || pwd; })"
cd "$HERE"

NAME="Vortex_HAGS_Selector"
RUNTIME="${RUNTIME:-C:/Users/RDC/AppData/Local/hermes/hermes-agent/.hermes-runtime/python/cpython-3.11.16-windows-x86_64-none}"
PY="${PY:-$HERE/_buildenv/Scripts/python.exe}"

echo "== 1. sync the rule from its canonical home =="
if [ -f "$HERE/../hags_policy.py" ]; then
  cp -f "$HERE/../hags_policy.py" "$HERE/hags_policy.py"
  echo "   copied ../hags_policy.py -> ./hags_policy.py"
else
  echo "   WARNING: canonical hags_policy.py not found; using the vendored copy"
fi

echo "== 2. tests (both suites) =="
python3 "$HERE/../test_hags_policy.py" 2>&1 | tail -2
python3 "$HERE/test_hags_selector.py" 2>&1 | tail -2
python3 vortex_hags_selector.py --selftest 2>&1 | tail -2

echo "== 3. the build environment =="
if [ ! -x "$PY" ]; then
  echo "   creating $PY from $RUNTIME"
  "$RUNTIME/python.exe" -m venv "$HERE/_buildenv"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet nuitka
fi
TCL="$("$PY" -c "import tkinter as tk; r=tk.Tk(); r.withdraw(); print(r.tk.eval('info library')); r.destroy()")"
echo "   tcl library: $TCL"
case "$TCL" in
  //zipfs*|"") echo "   FATAL: this interpreter has no Tcl directory on disk."; exit 1 ;;
esac

echo "== 4. nuitka =="
"$PY" -m nuitka \
  --standalone --onefile \
  --windows-disable-console \
  --windows-uac-admin \
  --enable-plugin=tk-inter \
  --tcl-library-dir="$TCL" \
  --windows-icon-from-ico="$HERE/app_icon.ico" \
  --include-data-files="$HERE/app_icon.ico=app_icon.ico" \
  --company-name="Vortex Industries" \
  --product-name="Vortex HAGS Selector" \
  --file-version=1.0.0.0 \
  --product-version=1.0.0.0 \
  --file-description="Hardware-Accelerated GPU Scheduling, decided per game" \
  --assume-yes-for-downloads \
  --output-filename="$NAME.exe" \
  "$HERE/vortex_hags_selector.py"

echo "== 5. verify the build, not the exit code =="
EXE="$HERE/$NAME.exe"
[ -f "$EXE" ] || { echo "   FATAL: no exe produced"; exit 1; }
ls -la "$EXE"
if [ -d "$HERE/vortex_hags_selector.dist" ]; then
  ls "$HERE/vortex_hags_selector.dist/tcl/init.tcl" >/dev/null 2>&1 \
    && echo "   tcl/init.tcl is present in the dist tree" \
    || echo "   WARNING: tcl/init.tcl missing from the dist tree"
fi
echo "== done =="
