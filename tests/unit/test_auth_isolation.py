from __future__ import annotations

from pathlib import Path

import pytest

from retropyclip.config import AppPaths
from retropyclip.sync.auth import KEYRING_ACCOUNT, CredentialStore


def test_isolated_home_uses_scoped_keyring_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RETROPYCLIP_HOME", str(tmp_path / "demo"))
    paths = AppPaths.discover()
    store = CredentialStore(paths)
    seen: list[str] = []

    def fake_get(service: str, account: str) -> None:
        seen.append(account)
        return None

    monkeypatch.setattr("retropyclip.sync.auth.keyring.get_password", fake_get)
    assert store.load(refresh=False) is None
    assert seen == [store._keyring_account()]
    assert seen[0] != KEYRING_ACCOUNT
    assert seen[0].startswith(f"{KEYRING_ACCOUNT}:")


def test_default_home_keeps_legacy_keyring_account(
    monkeypatch: pytest.MonkeyPatch, app_paths: AppPaths
) -> None:
    monkeypatch.delenv("RETROPYCLIP_HOME", raising=False)
    store = CredentialStore(app_paths)
    assert store._keyring_account() == KEYRING_ACCOUNT
