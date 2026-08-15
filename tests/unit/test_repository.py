from __future__ import annotations

from datetime import UTC, datetime, timedelta

from retropyclip.core.models import Record, RecordKind, SyncState, uuid7
from retropyclip.core.text import local_content_hash
from retropyclip.storage.sqlite import Repository


def add(repository: Repository, text: str, *, limit: int = 120, when=None):  # type: ignore[no-untyped-def]
    return repository.create_local_clip(
        text,
        device_id="local-device",
        device_name="Mac",
        max_bytes=65_536,
        history_limit=limit,
        captured_at=when,
    )


def remote_clip(text: str, *, sequence: int = 1, when=None) -> Record:  # type: ignore[no-untyped-def]
    return Record(
        id=uuid7(),
        kind=RecordKind.CLIP,
        captured_at=when or datetime.now(UTC),
        device_id="remote-device",
        device_name="Ubuntu",
        sequence=sequence,
        text=text,
        content_hash=local_content_hash(text),
    )


def test_add_preserves_text_and_suppresses_immediate_duplicate(repository: Repository) -> None:
    first, created = add(repository, "  hello\r\nworld  ")
    duplicate, duplicate_created = add(repository, "  hello\nworld  ")
    assert created is True
    assert first is not None and first.record.text == "  hello\nworld  "
    assert duplicate_created is False
    assert duplicate is not None and duplicate.record.id == first.record.id
    assert repository.stats()["pending"] == 1


def test_same_text_after_another_clip_is_a_new_event(repository: Repository) -> None:
    first, _ = add(repository, "same")
    add(repository, "different")
    second, created = add(repository, "same")
    assert created is True
    assert first is not None and second is not None and first.record.id != second.record.id


def test_programmatic_clipboard_copy_is_suppressed(repository: Repository) -> None:
    original, _ = add(repository, "old selection")
    add(repository, "newer")
    repository.set_clipboard_suppression("old selection")
    selected, created = add(repository, "old selection")
    assert created is False
    assert original is not None and selected is not None
    assert selected.record.id == original.record.id


def test_retention_hides_old_items(repository: Repository) -> None:
    base = datetime(2026, 8, 15, tzinfo=UTC)
    for number in range(4):
        add(repository, str(number), limit=2, when=base + timedelta(seconds=number))
    assert [item.record.text for item in repository.list_history(limit=None)] == ["3", "2"]
    assert repository.stats()["active"] == 2


def test_remote_import_is_idempotent(repository: Repository) -> None:
    record = remote_clip("from Linux")
    assert repository.import_remote(record, "remote-file-1") is True
    assert repository.import_remote(record, "remote-file-1") is False
    item = repository.get(record.id)
    assert item is not None and item.sync_state is SyncState.REMOTE
    assert repository.stats()["active"] == 1


def test_tombstone_before_clip_prevents_resurrection(repository: Repository) -> None:
    clip = remote_clip("deleted while offline")
    tombstone = Record(
        id=uuid7(),
        kind=RecordKind.TOMBSTONE,
        captured_at=datetime.now(UTC),
        device_id="remote-device",
        device_name="Ubuntu",
        sequence=2,
        target_id=clip.id,
    )
    assert repository.import_remote(tombstone, "tombstone-file") is True
    assert repository.import_remote(clip, "clip-file") is True
    assert repository.get(clip.id) is None
    assert repository.get(clip.id, include_deleted=True) is not None


def test_clear_everywhere_creates_one_tombstone_per_active_clip(repository: Repository) -> None:
    add(repository, "one")
    add(repository, "two")
    count = repository.clear_everywhere(device_id="local-device", device_name="Mac")
    assert count == 2
    assert repository.stats()["active"] == 0
    assert len(repository.pending_records()) == 4
    assert repository.clear_everywhere(device_id="local-device", device_name="Mac") == 0


def test_clear_local_does_not_create_tombstones(repository: Repository) -> None:
    add(repository, "one")
    assert repository.clear_local() == 1
    assert repository.stats()["tombstones"] == 0


def test_resolve_accepts_unique_prefix(repository: Repository) -> None:
    item, _ = add(repository, "lookup")
    assert item is not None
    assert repository.resolve(item.record.id[:10]).record.id == item.record.id  # type: ignore[union-attr]
