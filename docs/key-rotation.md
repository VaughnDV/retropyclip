# Passphrase and key rotation

The 0.1 implementation is deliberately manual. There is no in-place re-encryption
of Drive objects, because records are immutable and a half-rotated dataset would
be worse than a documented wipe-and-reseed.

## When to rotate

- The passphrase may have been disclosed (shell history, shoulder surfing, env var).
- You are approaching the 2^32-message operational bound in [crypto.md](crypto.md).
- You want stronger Argon2 parameters than the original device chose.

## Recovery if the passphrase is lost

Ciphertext on Drive cannot be recovered without the passphrase. Local history is
still in the plaintext SQLite database on each device that has it.

1. On a device that still has local history, export with `retropyclip export`.
2. Treat the export as secret: it is mode `0600` plaintext.
3. Delete this application's Google Drive app data (Google Account → Data from
   apps) and delete local `history.sqlite3` plus the `keyinfo` metadata on every
   device, or start from a fresh `RETROPYCLIP_HOME`.
4. Import the export, choose a new passphrase, and sync from one device first.

## Rotation when you still know the passphrase

1. Pause capture and pause sync on every device (`retropyclip pause` and
   `retropyclip pause --sync`).
2. Sync once so every device has the same history.
3. Export on one device.
4. Remove Drive app data and local databases/keyinfo as above.
5. Import, then `retropyclip sync` on the first device with the new passphrase.
6. Join other devices with that same new passphrase. Do not upload from a second
   device until the first has published `retropyclip.keyinfo.v1.json`.

Keep `RETROPYCLIP_SYNC_PASSPHRASE` out of shell history. Prefer the interactive
prompt.
