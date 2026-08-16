# Secret and sensitive-data scan

Reviewed on 16 August 2026 against the current tree and full `git` history.

## Method

- Filename search for OAuth client files, token files, SQLite databases, logs, and recovery exports.
- Content search for private-key headers, Google refresh tokens, AWS-style keys, and `client_secret` JSON payloads.
- History search of every committed path and of high-signal token patterns.

## Findings

| Area | Result |
|---|---|
| `client_secret*.json`, `credentials*.json`, `token*.json` | Not present in the tree; ignored by `.gitignore` |
| Clipboard databases and recovery exports | Not present; `*.db`, `*.sqlite*`, `recovery*.txt`, `*.log` are ignored |
| Private keys | None found |
| Git history filenames | No credential, database, log, or recovery files were ever committed |
| Git history content | Hits are source identifiers such as `client_secret` in OAuth client-install code, not secret values |
| Working-tree matches | Documentation and OAuth plumbing only |

The only database-like file in the workspace was `.mypy_cache/*/cache.db`, which is a type-checker cache and is gitignored.

## Residual notes

- OS keyring entries are outside the repository. `RETROPYCLIP_HOME` isolates files on disk. Token lookup for an isolated home must not fall back to the operator's real keyring; that is a credential-store requirement, not a git-history finding.
- Do not commit OAuth client JSON, token files, databases, logs, or recovery material.
