# Privacy

RetroPyClip does not operate a server and does not include telemetry, crash
analytics, or advertising identifiers.

- Clipboard history stays in a local SQLite database on your machine.
- Optional sync uploads AES-256-GCM ciphertext to **your** Google Drive
  application data folder. Google can see file names, sizes, and timestamps, not
  clip plaintext, if the passphrase is strong.
- OAuth tokens stay in the OS keyring or a mode-`0600` local file.
- There is no RetroPyClip account and no hosted backend to delete. Removing the
  app, its data directory, and the Drive app-data folder removes what this
  software stored.

Do not submit real clipboard contents with a bug report.
