# Licence compatibility

Reviewed on 16 August 2026. RetroPyClip is MIT-licensed.

## First-party material

| Asset | Licence |
|---|---|
| Python package, tests, docs, SVG tray icons | MIT (`LICENSE`) |
| Bundled GNOME Shell extension (`packaging/gnome-shell-extension`) | MIT, original to this repository |

The extension talks to GNOME Shell at runtime. GNOME Shell / GJS are LGPL-licensed system components and are **not** bundled or redistributed here.

## Runtime dependencies

| Package | Licence | Notes |
|---|---|---|
| argon2-cffi | MIT | Core KDF |
| cryptography | Apache-2.0 OR BSD-3-Clause | AES-GCM |
| google-api-python-client | Apache-2.0 | Drive transport |
| google-auth | Apache-2.0 | |
| google-auth-oauthlib | Apache-2.0 | |
| keyring | MIT | |
| platformdirs | MIT | |
| typer | MIT | |
| pyobjc-* (macOS) | MIT | Darwin-only extras of the core install |

All of the above are OSI-approved and compatible with distributing an MIT application.

## Optional extra

| Package | Licence | Notes |
|---|---|---|
| PySide6 | LGPL-3.0-only | GUI extra only. Dynamically linked. Headless installs must not pull it. |

LGPL-3.0 is compatible with an MIT application that loads PySide6 as a shared library and does not statically mix it into a proprietary blob. Packaged GUI builds must keep PySide6 redistributable as a library (PyInstaller already stores it as bundled shared objects). Do not relicense PySide6 as MIT.

## Build and development tools

Ruff, mypy, pytest, pytest-cov, Hypothesis, hatchling, and PyInstaller are development or build tooling. They are not shipped inside the runtime wheel.

## Icons and fonts

Tray icons are original SVG assets in `src/retropyclip/assets/`. The history popup uses the system "Menlo" font by name on macOS and does not embed a font file.

## CI check

`make audit` and the scheduled CI job fail the release checklist if a newly added runtime dependency is not MIT, BSD, Apache-2.0, ISC, or PSF. PySide6 is allowed only in the `gui` extra.
