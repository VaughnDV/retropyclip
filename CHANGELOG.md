# Changelog

All notable changes to RetroPyClip are documented here. Versions before 0.1.0 are
unreleased prototype history.

## 0.1.0 - unreleased alpha

### Added

- Local text-only clipboard history with pause/resume, duplicate suppression, and tombstones.
- AES-256-GCM Drive `appDataFolder` sync with Argon2id passphrase wrapping.
- CLI, optional PySide6 tray, macOS history hotkey, and GNOME Wayland bridge.
- Showcase hardening: isolated demo homes, diagnostic sanitisation, coverage gates,
  pinned GitHub Actions, Dependabot, SBOM, and a safe synthetic demo.

### Security

- Local SQLite history remains plaintext by design; FileVault or LUKS is required.
- Isolated `RETROPYCLIP_HOME` profiles no longer inherit the operator keyring token.
