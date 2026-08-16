"""Fail CI if a runtime dependency uses a licence we have not reviewed."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "MIT",
    "BSD",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Apache-2.0",
    "Apache 2.0",
    "Apache License 2.0",
    "ISC",
    "PSF",
    "PSF-2.0",
    "Python-2.0",
    "HPND",
    "Unlicense",
    "MPL-2.0",
    "LGPL-3.0-only",
    "LGPL-3.0",
}
GUI_ONLY = {"pyside6", "shiboken6"}


def _declared_runtime() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    names = {item.split(";")[0].split(">=")[0].split("[")[0].strip().lower() for item in data["project"]["dependencies"]}
    names |= {
        item.split(";")[0].split(">=")[0].split("[")[0].strip().lower()
        for item in data["project"]["optional-dependencies"].get("gui", [])
    }
    return names


def _licence_ok(text: str) -> bool:
    upper = text.upper()
    return any(token.upper() in upper for token in ALLOWED)


def main() -> int:
    declared = _declared_runtime()
    problems: list[str] = []
    for name in sorted(declared):
        try:
            meta = metadata(name)
        except PackageNotFoundError:
            if name.startswith("pyobjc"):
                continue
            problems.append(f"{name}: not installed in this environment")
            continue
        licence = meta.get("License-Expression") or meta.get("License") or ""
        if name in GUI_ONLY:
            if licence and not _licence_ok(licence) and "LGPL" not in licence.upper():
                problems.append(f"{name}: unexpected GUI licence {licence!r}")
            continue
        if licence and not _licence_ok(licence):
            problems.append(f"{name}: unreviewed licence {licence!r}")
    if problems:
        print("Licence audit failed:")
        for item in problems:
            print(f"  - {item}")
        return 1
    print(f"Licence audit passed for {len(declared)} declared runtime packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
