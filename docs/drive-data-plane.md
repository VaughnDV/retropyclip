# Serverless Drive data plane

Staff-level design note: why RetroPyClip uses the user's private Google Drive
`appDataFolder` instead of operating a sync server.

## The trade-off

A hosted API would give us first-class conflict APIs, quota we control, and a
place to run garbage collection. It would also create an operated data plane:
accounts, availability, lawful intercept, and a honeypot of clipboard ciphertext
and metadata.

RetroPyClip instead treats Drive as an untrusted blob store. Clients encrypt
before upload, write immutable per-record files, and merge by identifier. The
operator of RetroPyClip never sees clips, keys, or OAuth refresh tokens.

## What this buys

- No RetroPyClip-operated server or telemetry (see [privacy.md](privacy.md)).
- The confidentiality boundary is the user's passphrase and devices, not our
  uptime or access-control list.
- Concurrent devices append; they do not edit one shared document.

## Operational limitations

- Google still sees object names, sizes, timestamps, and approximate volume.
- Weak passphrases can be guessed offline against ciphertext at rest on Drive.
- Tombstones hide history but do not immediately delete old ciphertext.
- Quota, OAuth policy, and seven-day testing-token expiry are Google's.
- Clients must be able to fail closed on unknown envelope versions.
- Support is "sync these devices", not "reset the server-side view".

Those limitations are acceptable for a private-first prototype and are exactly
the constraints a Staff interview should be able to defend: we chose a smaller
trusted computing base over a smoother product surface.
