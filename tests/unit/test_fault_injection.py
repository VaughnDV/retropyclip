from __future__ import annotations

import sqlite3

import pytest

from retropyclip.storage.sqlite import Repository


def test_failed_transaction_does_not_commit_partial_rows(repository: Repository) -> None:
    repository.create_local_clip(
        "kept",
        device_id="device",
        device_name="Mac",
        max_bytes=1024,
        history_limit=10,
    )
    with (
        pytest.raises(sqlite3.IntegrityError),
        repository.transaction() as connection,
    ):
        connection.execute("INSERT INTO meta(key, value) VALUES('partial', 'yes')")
        connection.execute("INSERT INTO meta(key, value) VALUES('partial', 'duplicate')")
    assert repository.get_meta("partial") is None
    assert repository.stats()["active"] == 1


def test_corrupt_settings_write_leaves_previous_file(app_paths, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from retropyclip.config import ConfigStore

    store = ConfigStore(app_paths)
    settings = store.load()
    original = app_paths.settings_file.read_text("utf-8")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    with pytest.raises(OSError, match="disk full"):
        store.save(settings)
    assert app_paths.settings_file.read_text("utf-8") == original
