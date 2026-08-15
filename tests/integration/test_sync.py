from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from retropyclip.crypto.envelope import CryptoError, KDFParameters, KeyInfo
from retropyclip.storage.sqlite import Repository
from retropyclip.sync.backend import MemoryBackend, TransientBackendError
from retropyclip.sync.engine import SyncEngine

PASSPHRASE = "shared and reasonably long passphrase"
FAST_KDF = KDFParameters(time_cost=1, memory_cost_kib=64, parallelism=1)


def repo(path: Path, name: str) -> Repository:
    return Repository(path / name / "history.sqlite3")


def add(repository: Repository, text: str, device: str) -> None:
    repository.create_local_clip(
        text,
        device_id=device,
        device_name=device,
        max_bytes=65_536,
        history_limit=120,
        captured_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
    )


def engine(repository: Repository, backend: MemoryBackend) -> SyncEngine:
    return SyncEngine(
        repository,
        backend,
        max_item_bytes=65_536,
        history_limit=120,
        sleeper=lambda _: None,
        kdf_parameters=FAST_KDF,
    )


def test_two_devices_copying_at_same_time_both_survive(tmp_path: Path) -> None:
    remote = MemoryBackend()
    mac = repo(tmp_path, "mac")
    linux = repo(tmp_path, "linux")
    add(mac, "copied on Mac", "mac-device")
    add(linux, "copied on Linux", "linux-device")

    assert engine(mac, remote).sync(PASSPHRASE).pushed == 1
    linux_report = engine(linux, remote).sync(PASSPHRASE)
    assert linux_report.pulled == 1
    assert linux_report.pushed == 1
    assert engine(mac, remote).pull(PASSPHRASE).pulled == 1

    expected = {"copied on Mac", "copied on Linux"}
    assert {item.record.text for item in mac.list_history(limit=None)} == expected
    assert {item.record.text for item in linux.list_history(limit=None)} == expected


def test_downloaded_record_is_not_queued_for_reupload(tmp_path: Path) -> None:
    remote = MemoryBackend()
    first = repo(tmp_path, "first")
    second = repo(tmp_path, "second")
    add(first, "only one event", "first-device")
    engine(first, remote).sync(PASSPHRASE)
    file_count = len(remote.list_objects())
    report = engine(second, remote).sync(PASSPHRASE)
    assert report.pulled == 1
    assert report.pushed == 0
    assert len(remote.list_objects()) == file_count
    assert second.stats()["pending"] == 0


def test_clear_everywhere_propagates_tombstone(tmp_path: Path) -> None:
    remote = MemoryBackend()
    first = repo(tmp_path, "first")
    second = repo(tmp_path, "second")
    add(first, "erase me", "first-device")
    engine(first, remote).sync(PASSPHRASE)
    engine(second, remote).sync(PASSPHRASE)
    assert second.stats()["active"] == 1

    assert first.clear_everywhere(device_id="first-device", device_name="Mac") == 1
    engine(first, remote).sync(PASSPHRASE)
    engine(second, remote).sync(PASSPHRASE)
    assert second.stats()["active"] == 0


def test_corrupt_remote_record_is_rejected_and_remembered(tmp_path: Path) -> None:
    remote = MemoryBackend()
    first = repo(tmp_path, "first")
    engine(first, remote).sync(PASSPHRASE)
    remote.upload("bad.rpc.json", b"not encrypted JSON")
    report = engine(first, remote).pull(PASSPHRASE)
    assert len(report.errors) == 1
    again = engine(first, remote).pull(PASSPHRASE)
    assert len(again.errors) == 0


def test_transient_list_failure_retries(tmp_path: Path) -> None:
    class FlakyBackend(MemoryBackend):
        calls = 0

        def list_objects(self):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls < 3:
                raise TransientBackendError("temporary")
            return super().list_objects()

    remote = FlakyBackend()
    first = repo(tmp_path, "first")
    report = SyncEngine(
        first,
        remote,
        max_item_bytes=65_536,
        history_limit=120,
        sleeper=lambda _: None,
        kdf_parameters=FAST_KDF,
    ).sync(PASSPHRASE)
    assert report.errors == ()
    assert remote.calls >= 3


def test_identical_keyinfo_retry_duplicates_are_tolerated(tmp_path: Path) -> None:
    remote = MemoryBackend()
    info, _ = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    raw = info.to_json()
    remote.upload("retropyclip.keyinfo.v1.json", raw)
    remote.upload("retropyclip.keyinfo.v1.json", raw)
    first = repo(tmp_path, "first")
    assert engine(first, remote).sync(PASSPHRASE).errors == ()


def test_conflicting_initial_keyinfo_is_rejected_before_push(tmp_path: Path) -> None:
    remote = MemoryBackend()
    first_info, _ = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    second_info, _ = KeyInfo.create(PASSPHRASE, parameters=FAST_KDF)
    remote.upload("retropyclip.keyinfo.v1.json", first_info.to_json())
    remote.upload("retropyclip.keyinfo.v1.json", second_info.to_json())
    first = repo(tmp_path, "first")
    add(first, "must remain local", "first-device")
    with pytest.raises(CryptoError, match="multiple sync key configurations"):
        engine(first, remote).sync(PASSPHRASE)
    assert first.stats()["pending"] == 1
