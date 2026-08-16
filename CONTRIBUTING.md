# Contributing

Thank you for considering a change to RetroPyClip. This is a security-sensitive
clipboard tool. Prefer synthetic text in issues, tests, and screenshots.

## Development

Python 3.12+ and `uv` are required:

```bash
uv sync --all-extras
make check
make test
```

Underlying commands, if you do not want Make:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Install git hooks with `uvx pre-commit install` (or `pre-commit install` if you
already have it). Hooks run Ruff, mypy for the typed core, standard file checks,
and reject credential filenames.

## Scope

- Keep the product text-only. Do not add image or file clipboard capture.
- Do not claim Windows support without an adapter, CI job, and real-device row.
- Remote records stay immutable. Do not introduce a shared mutable Drive file.
- Never log clipboard text, passphrases, derived keys, or OAuth tokens.
- GUI code lives behind the `gui` extra. Headless installs must stay slim.

The name `RetroPyClip` is distinct from the `pyclip` library. Do not treat them
as interchangeable in docs or import examples.

## Pull requests

- Add tests for crypto, storage, and sync changes.
- Update `CHANGELOG.md` for user-visible behaviour.
- Use synthetic clipboard strings only.
