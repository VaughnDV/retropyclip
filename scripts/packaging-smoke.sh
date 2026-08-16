#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
uv build --out-dir "$work/dist"
wheel="$(python3 -c "import pathlib; print(next(pathlib.Path(r'''$work/dist''').glob('*.whl')))")"
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip install --quiet "$wheel"
"$work/venv/bin/python" -c "import retropyclip; print(retropyclip.__version__)"
"$work/venv/bin/python" - <<'PY'
import importlib.util
import sys

if importlib.util.find_spec("PySide6") is not None:
    sys.exit("PySide6 leaked into the headless install")
print("headless wheel is free of PySide6")
PY
