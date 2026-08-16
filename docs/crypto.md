# Encrypted record format

This is the on-the-wire format for Google Drive `appDataFolder` objects. Local SQLite
history is **not** in this envelope; see [at-rest-encryption.md](at-rest-encryption.md).

## Versioning

| Object | Schema string | Filename |
|---|---|---|
| Encrypted record | `retropyclip.record/1` | `<uuid>.rpc.json` |
| Inner payload | `retropyclip.payload/1` | (inside ciphertext) |
| KDF metadata | `retropyclip.keyinfo/1` | `retropyclip.keyinfo.v1.json` |

Unknown `schema` values are rejected. Extra JSON fields are rejected. A future
incompatible format must use a new schema string so old clients fail closed instead
of mis-parsing ciphertext.

## Algorithms

| Role | Identifier | Parameters |
|---|---|---|
| KDF | `argon2id` | time_cost default 3, memory_cost_kib 65536, parallelism 2, hash_len 32 |
| AEAD | AES-256-GCM | 32-byte key, 12-byte nonce, 16-byte tag (appended by GCM) |
| Verifier | HMAC-SHA256 | key = derived AES key, message = `retropyclip key verifier/1` |
| Content hash (remote) | HMAC-SHA256 | key = derived AES key, message = `retropyclip content hash/1\x00` \\| utf-8 text |

## Envelope fields (`retropyclip.record/1`)

```json
{
  "schema": "retropyclip.record/1",
  "id": "<record uuid>",
  "kind": "clip" | "tombstone",
  "nonce": "<base64 12-byte nonce>",
  "ciphertext": "<base64 GCM ciphertext+tag>"
}
```

`id` and `kind` are unencrypted so listing and tombstone debugging can run without
the passphrase. They are also bound as associated data, so swapping them is an
authentication failure.

## Associated data

```
UTF-8:  retropyclip.record/1  ||  0x00  ||  record_id  ||  0x00  ||  kind
```

GCM authenticates this AAD together with the ciphertext. A truncated file, a bit
flip, a swapped id, or a swapped kind fails `record authentication failed`.

## Nonce uniqueness

Every `encrypt` call draws 12 bytes from `os.urandom`. RetroPyClip does not use a
message counter.

- AES-GCM nonce reuse with the same key is catastrophic. Random 96-bit nonces are
  the NIST-recommended approach for this volume.
- A birthday collision becomes plausible around 2^48 messages under one key.
  Clipboard history is capped far below 2^32 records per passphrase lifetime.
- Operational bound: rotate the passphrase (see [key-rotation.md](key-rotation.md))
  before encrypting 2^32 records under one derived key. The application never
  reuses a caller-supplied nonce in production; tests may inject a nonce only to
  pin known-answer vectors.

## Key metadata (`retropyclip.keyinfo/1`)

Published fields: `kdf`, `salt`, `time_cost`, `memory_cost_kib`, `parallelism`,
`verifier`. None of these is secret. The passphrase and the 32-byte AES key never
leave the device and are never uploaded.

## Python memory limitations

Passphrases, derived keys, and plaintext records live in CPython objects. The
runtime can intern strings, copy during resize, leave values in GC heaps, and
write them to swap or crash dumps. RetroPyClip overwrites a few local names after
use in the tray passphrase prompt; that is best-effort hygiene, **not**
zeroisation. Do not claim that secrets can always be erased from process memory.
