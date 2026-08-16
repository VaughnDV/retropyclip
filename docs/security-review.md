# Focused security review

Reviewed on 16 August 2026. Scope: encryption, key derivation, token storage, file permissions, sync conflict handling, and clipboard exposure. This is an in-tree engineering review, not a commissioned audit.

## Encryption and key derivation

- Remote records use AES-256-GCM with a 12-byte CSPRNG nonce and associated data binding schema, record id, and kind.
- The wrapping key is Argon2id (`argon2id`, 32-byte output) from a user passphrase, random 16-byte salt, and published work parameters.
- Key metadata (`retropyclip.keyinfo/1`) is non-secret and includes an HMAC verifier so a wrong passphrase fails closed before records are parsed.
- Envelope schema `retropyclip.record/1` and payload schema `retropyclip.payload/1` reject unknown fields and version mismatches.
- GCM authentication failures, truncated records, and identity mismatches between envelope and payload are rejected and remembered so hostile remotes cannot retry forever.

No high-risk cryptographic defect was found in this design. Residual risks are weak passphrases (offline guessing against Drive ciphertext) and Python's inability to guarantee secret zeroisation.

## Token storage

- OAuth is limited to `drive.appdata`.
- Tokens prefer the OS keyring and fall back to a mode-`0600` file under the private config directory.
- Isolated `RETROPYCLIP_HOME` profiles use a path-scoped keyring account so a demo home cannot read the operator's real Google token.

## File permissions

- Config, data, and cache directories are created mode `0700`.
- Settings, token fallback, client secrets, databases, and recovery exports are mode `0600`.
- The Ubuntu updater writes its diagnostic log mode `0600` under `~/.local/state/retropyclip/`.
- `doctor` checks database permission bits.

## Sync conflict handling

- Remote objects are immutable one-file-per-record files. Concurrent devices append; they do not edit a shared document.
- Merge is by record id. Tombstones hide clips even if the clip arrives later.
- Conflicting initial key-metadata files fail closed and refuse to upload clips.
- Clock skew can change presentation order; it cannot resurrect a tombstoned id.

## Clipboard exposure

- Capture is text-only. Images and files are not stored.
- Pause/resume is persistent and honoured by the daemon, tray, and GNOME bridge callback path.
- Copying an old item suppresses recapture; it does not create a duplicate or reset retention.
- Concealed pasteboard markers are honoured on macOS and by the GNOME bridge when the compositor exposes them.
- The GNOME D-Bus bridge listens only on the per-user session bus. A process running as the same logged-in user can still send `CaptureText`; that is inside the local-endpoint threat model.

## Decision on local at-rest encryption

Application-level encryption of the local SQLite history is **not** implemented in this alpha. The local machine is trusted while the user session is unlocked. Disk encryption (FileVault or LUKS) is required. See [at-rest-encryption.md](at-rest-encryption.md).

## Findings

| Severity | Item | Status |
|---|---|---|
| Medium | Isolated `RETROPYCLIP_HOME` could inherit the operator keyring token | Fixed: path-scoped keyring account |
| Medium | Tray Sync Now stayed enabled while `sync_paused` | Fixed: tray and engine both refuse |
| Low | `mkdir(..., exist_ok=True)` does not tighten already-too-open directories | Fixed: `ensure_private_dir` |
| Low | Sync error strings include exception text from remote parsing | Fixed: `sanitize_diagnostic` |
| Info | Python cannot reliably zeroise passphrases or AES keys | Documented; not claimed |

No unresolved high-risk findings remain in this review. Commission an independent review before a non-alpha public release if the threat model grows (App Store distribution, Windows, or hosted components).
