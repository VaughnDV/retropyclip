# Local at-rest encryption decision

## Decision

RetroPyClip 0.1 **does not** encrypt the local SQLite history. Local clipboard text is stored in plaintext under the platform user-data directory (or `RETROPYCLIP_HOME`). Remote Drive objects **are** encrypted with AES-256-GCM.

This is an explicit product boundary, not an accidental omission.

## Why the local database stays plaintext

- History search, tray rendering, and CLI `show`/`copy` need the plaintext on every keystroke of an unlocked session. An application key would have to remain in memory for the same period the OS already considers the user session trusted.
- FileVault (macOS) or LUKS (Linux) already encrypts the disk blocks that hold `history.sqlite3`, settings, and token fallback files when the machine is powered off or the disk is removed.
- SQLCipher or a homemade page-encryption layer would add a second passphrase, migration risk, and a new supply-chain dependency without changing the unlocked-session threat model.
- The README, threat model, and `doctor` output state this residual risk instead of implying application-level local encryption.

## Residual risk

Anyone who can read the user's files while the session is unlocked — malware running as the user, another process with the same uid, a debugger, or an unsound backup of the data directory — can read clipboard history. Pause capture before handling known secrets. Use OS disk encryption. Do not treat local history as a password manager.

## Revisit when

- A locked-session or screen-locked disclosure requirement appears.
- Packaged builds need to survive unencrypted backup targets.
- An independent review recommends SQLCipher (or equivalent) *and* a key-management story that is stronger than "the key sits in RAM while you work".
