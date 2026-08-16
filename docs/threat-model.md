# Threat model

## Protected assets

- Clipboard text and its metadata.
- Google OAuth refresh tokens.
- The sync passphrase and derived encryption key.
- Local history and device identity.

## Security boundaries

Google Drive is treated as an untrusted storage layer for clipboard content.
Remote record bodies are encrypted and authenticated with AES-256-GCM. The record
ID, record kind, file size, upload time, KDF salt, and rough activity volume remain
visible to Google. The passphrase must be strong enough to resist offline guessing.

The local machine is trusted while the user session is unlocked. RetroPyClip's
SQLite database deliberately stores plaintext for fast local operation. This is a
documented product decision, not a missing feature: see
[at-rest-encryption.md](at-rest-encryption.md). FileVault or LUKS is required for
local at-rest protection. Malware running as the user, screen readers with
excessive access, clipboard snoopers, debuggers, and physical access to an
unlocked device are outside the encryption boundary.

## Main risks and mitigations

| Risk | Mitigation | Residual limitation |
|---|---|---|
| Drive data disclosure | Argon2id + AES-256-GCM before upload | Weak passphrases can be guessed offline |
| Remote tampering | GCM authentication and strict schemas | Attackers can delete or replay files |
| Concurrent writes | Immutable per-record files and ID merge | Clock skew changes presentation order |
| Token theft | OS keyring; `0600` fallback | Compromised user sessions can read credentials |
| Secret clipboard capture | Pause controls and concealed-marker hooks where possible | Generic text cannot reliably be identified as a secret |
| Log leakage | Sensitive text, tokens, passphrases, and keys are never logged | Crash tools and OS diagnostics need separate review |
| Oversized/malformed records | Size caps, schema checks, authenticated parsing | Listing a very large hostile dataset can still cost time |

## Deletion

"Clear local" only hides local history. "Clear everywhere" creates immutable
encrypted tombstones, ensuring an offline device's old clip does not resurrect after
it reconnects. Old ciphertext remains in Drive until a future garbage-collection
feature deletes files; users requiring immediate physical deletion should remove the
application's Drive data and local databases on every device.

## Before public release

Commission review of cryptographic usage, OAuth token handling, local file
permissions, dependency provenance, packaging, macOS Accessibility behaviour, and
Wayland capability fallbacks. Add automated dependency and secret scanning without
claiming either detects every vulnerability.
