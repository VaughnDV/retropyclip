# RetroPyClip

RetroPyClip is a private-first, text-only clipboard history application for macOS,
Ubuntu, and Raspberry Pi. It stores history locally in SQLite and can synchronize
encrypted immutable records through the user's private Google Drive app-data area.
There is no RetroPyClip-operated server.

> **Prototype warning:** Clipboard history often contains passwords, access tokens,
> personal data, and source code. Review the [threat model](docs/threat-model.md)
> before using this build with real data.
>
> **Local history is not application-encrypted.** The SQLite database is plaintext
> by design so search and the tray can run in an unlocked session. Use FileVault
> or LUKS. Remote Drive records *are* AES-256-GCM encrypted. See
> [at-rest-encryption.md](docs/at-rest-encryption.md).

![RetroPyClip history console](docs/assets/history-console.png)

Capture, filter, and copy are local. Encrypted sync is optional and uses your Drive
app-data folder. A 30–60 second recording of `make demo` is the preferred motion
asset; the screenshot above is synthetic demo data only. The four-step storyboard
is [docs/assets/demo-flow.svg](docs/assets/demo-flow.svg). Record `make demo` for a
live 30–60 second GIF before a public launch.

## Architecture

Clipboard adapters, the SQLite repository, the AES-GCM envelope, Drive transport,
and the CLI/tray are separate. See [docs/architecture.md](docs/architecture.md)
and the Staff-level note on a [serverless Drive data plane](docs/drive-data-plane.md).

## Security properties / not protected against

| Protected | Not protected against |
|---|---|
| Clip plaintext on Drive, given a strong passphrase | Weak passphrases |
| Authenticated remote records | Drive deletion or replay |
| Concurrent-device merge and tombstones | Clock skew in display order |
| Keyring / `0600` token files | Malware in an unlocked user session |
| Pause and text-only capture | Secrets that look like ordinary text |
| Isolated demo homes | Local DB without FileVault or LUKS |

Full model: [docs/threat-model.md](docs/threat-model.md). Privacy: there is no
operated server or telemetry ([docs/privacy.md](docs/privacy.md)).

## What works in this MVP

- Local text-only clipboard history with deterministic ordering and a configurable
  120-item default retention limit.
- Immediate duplicate suppression, pause/resume, exact copy/show, JSON and text
  export/import, local clearing, and tombstone-based "clear everywhere".
- AES-256-GCM record encryption with an Argon2id passphrase-derived key.
- Immutable one-file-per-record synchronization through Google Drive
  `appDataFolder`, including offline-safe retry and remote deduplication.
- The same Typer CLI on every platform.
- Clipboard adapters for macOS (`pbcopy`/`pbpaste`), X11 (`xclip` or `xsel`),
  Wayland (`wl-copy`/`wl-paste`), and a headless CLI workflow.
- An optional PySide6 tray application with grouped history and retro pixel icons.

## Install for development

Python 3.12 or newer and `uv` are recommended:

```bash
cd /path/to/retropyclip
uv sync --all-extras
uv run retropyclip doctor
make check
make test
```

`make check`, `make test`, `make package`, `make audit`, and `make demo` wrap the
same `uv` commands. See [CONTRIBUTING.md](CONTRIBUTING.md).

For a smaller headless installation, omit `--all-extras`:

```bash
uv sync
uv run retropyclip add "hello from this device"
uv run retropyclip history
```

On Ubuntu X11 install either `xclip` or `xsel`. On Wayland install `wl-clipboard`.
A genuinely headless Pi needs neither; use `add`, `show`, `push`, and `pull`.

Wayland clipboard watching uses the compositor's data-control protocol on desktops
such as Sway and Hyprland. Standard Ubuntu GNOME Wayland does not expose that
protocol to ordinary applications, so `ubuntu-update.sh` installs a small bundled
GNOME Shell bridge that forwards text to the local RetroPyClip process over the
private desktop session bus. The first installation may ask for one logout/login to
load the extension. RetroPyClip never repeatedly polls `wl-paste`, because its
fallback window can visibly flash on unsupported compositors.

After cloning on an Ubuntu desktop, future updates can be installed and the tray
restarted with:

```bash
git pull --ff-only
./ubuntu-update.sh
```

The updater installs a missing X11/Wayland clipboard utility through `apt`, refreshes
the locked Python environment, runs `doctor`, and restarts only this checkout's tray
process. Its diagnostic log is stored privately under `~/.local/state/retropyclip/`.

## Quick local use

```bash
retropyclip add "hello"
printf 'piped text' | retropyclip add
retropyclip history
retropyclip show ITEM_ID
retropyclip copy ITEM_ID
retropyclip daemon
```

`daemon` watches the desktop clipboard and records text changes until interrupted.
It never captures images or files. Use `retropyclip pause --minutes 5` before
handling known-sensitive material.

## Enable Google Drive sync

Real Drive sync requires an OAuth client that you create in your own Google Cloud
project. Follow [docs/google-oauth-setup.md](docs/google-oauth-setup.md), then:

```bash
retropyclip login --client-secrets /safe/path/client_secret.json
retropyclip sync
```

The first sync asks for a sync passphrase and creates non-secret Argon2id key
metadata in `appDataFolder`. Enter the same passphrase on every device. The
passphrase and derived key are never uploaded. For unattended use, provide the
passphrase through `RETROPYCLIP_SYNC_PASSPHRASE`; understand that environment
variables can be exposed to other processes owned by the same user.

Run `retropyclip status` for local state and authentication readiness. Downloaded
clips enter history but never replace the current clipboard automatically.

## Optional tray app

```bash
uv sync --extra gui
uv run retropyclip-tray
```

The tray menu includes grouped history, Sync Now, pause controls, clearing, and
preferences. On macOS, `Cmd+Shift+V` opens a compact retro history console from any
application. Type to filter, use Up/Down to browse, then press Enter or click an item
to paste the exact plain text back into the application you were using. Escape closes
the window, and pressing the shortcut again toggles it.

The shortcut itself uses native macOS hotkey registration and does not need extra
access. Automatic paste does: the first selection asks for Accessibility permission.
Open **System Settings → Privacy & Security → Accessibility** and enable
RetroPyClip. During development, macOS may list it as Python or the terminal app that
launched it (for example, Warp). If the picker was already running, restart it after
granting access. A selection is still copied to the clipboard when permission is not
available, so regular `Cmd+V` remains a fallback.

Packaging, signing, notarisation, launch-at-login, configurable shortcuts, and a
Linux-wide shortcut implementation remain release work rather than prototype claims.

## Data locations

Platform-standard user data and configuration locations are selected with
`platformdirs`. For isolated testing, set `RETROPYCLIP_HOME` to a directory. OAuth
tokens use the OS keyring when available and fall back to a mode-`0600` file.

Do not commit OAuth client files, token files, databases, logs, or recovery material.

## Project status

This repository implements the Stage 1 sync core plus an early Stage 2/3 tray and
daemon experience. Public-release notes:

- Name clearance: [docs/name-clearance.md](docs/name-clearance.md)
- Secret scan: [docs/secret-scan.md](docs/secret-scan.md)
- Security review: [docs/security-review.md](docs/security-review.md)
- Licence audit: [docs/license-audit.md](docs/license-audit.md)
- Compatibility matrix: [docs/compatibility-matrix.md](docs/compatibility-matrix.md)
- Real-device checklist: [docs/feasibility-checklist.md](docs/feasibility-checklist.md)
- Troubleshooting: [docs/troubleshooting.md](docs/troubleshooting.md)
- Contributing / changelog / roadmap: [CONTRIBUTING.md](CONTRIBUTING.md),
  [CHANGELOG.md](CHANGELOG.md), [docs/roadmap.md](docs/roadmap.md)
- Safe synthetic demo: `make demo` (isolated `RETROPYCLIP_HOME`, no real OAuth)
