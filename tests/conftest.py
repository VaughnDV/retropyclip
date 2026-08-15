from __future__ import annotations

from pathlib import Path

import pytest

from retropyclip.config import AppPaths, ConfigStore
from retropyclip.storage.sqlite import Repository


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    config = tmp_path / "config"
    data = tmp_path / "data"
    cache = tmp_path / "cache"
    return AppPaths(
        config_dir=config,
        data_dir=data,
        cache_dir=cache,
        settings_file=config / "settings.json",
        database_file=data / "history.sqlite3",
        token_file=config / "token.json",
        client_secrets_file=config / "client.json",
    )


@pytest.fixture
def settings(app_paths: AppPaths):  # type: ignore[no-untyped-def]
    return ConfigStore(app_paths).load()


@pytest.fixture
def repository(app_paths: AppPaths) -> Repository:
    return Repository(app_paths.database_file)
