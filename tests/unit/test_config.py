from __future__ import annotations

import json

import pytest

from retropyclip.config import AppPaths, ConfigStore


def test_config_store_creates_private_settings(app_paths: AppPaths) -> None:
    store = ConfigStore(app_paths)
    settings = store.load()
    assert settings.history_limit == 120
    assert settings.device_id
    assert app_paths.settings_file.exists()
    assert app_paths.settings_file.stat().st_mode & 0o077 == 0


def test_config_rejects_bad_limits(app_paths: AppPaths) -> None:
    store = ConfigStore(app_paths)
    settings = store.load()
    settings.history_limit = 0
    with pytest.raises(ValueError, match="history limit"):
        store.save(settings)


def test_environment_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RETROPYCLIP_HOME", str(tmp_path / "isolated"))
    paths = AppPaths.discover()
    assert paths.config_dir == (tmp_path / "isolated" / "config").resolve()


def test_corrupt_settings_fail_closed(app_paths: AppPaths) -> None:
    app_paths.config_dir.mkdir(parents=True)
    app_paths.settings_file.write_text(json.dumps({"schema": 1}), "utf-8")
    with pytest.raises(RuntimeError, match="cannot load settings"):
        ConfigStore(app_paths).load()
