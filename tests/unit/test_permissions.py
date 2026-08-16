from __future__ import annotations

import os
from pathlib import Path

from retropyclip.config import AppPaths, ConfigStore, ensure_private_dir
from retropyclip.storage.sqlite import Repository
from retropyclip.sync.auth import install_client_secrets


def test_existing_open_directories_are_tightened(tmp_path: Path) -> None:
    home = tmp_path / "open"
    config = home / "config"
    data = home / "data"
    cache = home / "cache"
    config.mkdir(parents=True)
    data.mkdir(parents=True)
    cache.mkdir(parents=True)
    os.chmod(config, 0o755)
    os.chmod(data, 0o755)
    paths = AppPaths(
        config_dir=config,
        data_dir=data,
        cache_dir=cache,
        settings_file=config / "settings.json",
        database_file=data / "history.sqlite3",
        token_file=config / "token.json",
        client_secrets_file=config / "client.json",
    )
    ConfigStore(paths).load()
    assert config.stat().st_mode & 0o777 == 0o700
    assert data.stat().st_mode & 0o777 == 0o700
    assert paths.settings_file.stat().st_mode & 0o077 == 0


def test_database_and_export_are_mode_600(tmp_path: Path) -> None:
    database = tmp_path / "data" / "history.sqlite3"
    repository = Repository(database)
    repository.create_local_clip(
        "secret",
        device_id="device",
        device_name="Mac",
        max_bytes=1024,
        history_limit=10,
    )
    assert database.stat().st_mode & 0o777 == 0o600
    wal = Path(str(database) + "-wal")
    if wal.exists():
        assert wal.stat().st_mode & 0o077 == 0


def test_oauth_client_copy_is_private(tmp_path: Path, app_paths: AppPaths) -> None:
    source = tmp_path / "client_secret.json"
    source.write_text('{"installed": {"client_id": "demo"}}', "utf-8")
    os.chmod(source, 0o644)
    installed = install_client_secrets(source, app_paths)
    assert installed.stat().st_mode & 0o777 == 0o600


def test_ensure_private_dir_creates_0700(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "state"
    ensure_private_dir(target)
    assert target.is_dir()
    assert target.stat().st_mode & 0o777 == 0o700
