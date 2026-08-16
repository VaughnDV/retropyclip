# Compatibility matrix

Synthetic clipboard text only. No real passwords, tokens, or personal data. Dated 16 August 2026.

| Platform | OS / session | Arch | Python | Adapter | Capture | Copy/show | Doctor | Drive round-trip | Notes |
|---|---|---|---|---|---|---|---|---|---|
| macOS | macOS 26.5.2, Aqua | arm64 | 3.12.3 (uv) | pbcopy/pbpaste | Pass (`add` synthetic item) | Pass (`history --json`, `show`) | Pass: DB `0600`, concealed markers supported | Not run (no dedicated OAuth client in this pass) | Workstation used for this matrix |
| Ubuntu X11 | CI `ubuntu-latest` plus unit/integration tests | x86_64 | 3.12, 3.13 | xclip/xsel when present | Automated tests cover repository/CLI, not a physical X11 session | Automated | CI `doctor` is not a desktop session | Memory-backend integration tests | Real X11 box still required before calling the GUI generally available |
| Ubuntu GNOME Wayland | Not executed on a physical GNOME box in this pass | — | — | GNOME session-bus bridge | Bridge unit-tested | — | — | — | Install path is `ubuntu-update.sh`; needs a logout/login on first enable |
| Raspberry Pi / headless | Not executed on physical Pi hardware in this pass | — | — | headless CLI | `add`/`history`/`show` covered by CLI tests | Pass in CI | Headless clipboard is a warning, not a hard failure, by design | Memory-backend tests | Physical ARM64 confirmation remains a release gate |

## macOS workstation commands (synthetic)

```bash
RETROPYCLIP_HOME=./tmp/showcase-home uv run retropyclip doctor
RETROPYCLIP_HOME=./tmp/showcase-home uv run retropyclip add "synthetic-macos-matrix-2026-08-16"
RETROPYCLIP_HOME=./tmp/showcase-home uv run retropyclip history --json
```

Doctor reported Python 3.12.3, database mode `0600`, Aqua pbcopy/pbpaste, and concealed-marker support. The added item round-tripped through `history` with an exact preview of the synthetic string.

## Still required on real hardware

- Ubuntu X11 capture via `xclip` or `xsel` in a logged-in desktop session.
- Ubuntu GNOME Wayland capture via the bundled session-bus bridge after one logout/login.
- Raspberry Pi desktop and headless `doctor` plus `add`/`show`.
- One-account Drive round-trip from [feasibility-checklist.md](feasibility-checklist.md).

Until those four rows are filled, packaged GUI builds should remain labelled alpha. Core, integration, and packaging tests are still required to pass in CI.
