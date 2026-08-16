from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from retropyclip.crypto.envelope import KDFParameters
from retropyclip.storage.sqlite import Repository
from retropyclip.sync.backend import MemoryBackend
from retropyclip.sync.engine import SyncEngine

PASSPHRASE = "shared and reasonably long passphrase"
FAST_KDF = KDFParameters(time_cost=1, memory_cost_kib=32, parallelism=1)
labels = st.lists(st.sampled_from(["a", "b", "c", "d", "e"]), min_size=1, max_size=5)


def _engine(repository: Repository, backend: MemoryBackend) -> SyncEngine:
    return SyncEngine(
        repository,
        backend,
        max_item_bytes=65_536,
        history_limit=120,
        sleeper=lambda _: None,
        kdf_parameters=FAST_KDF,
    )


@given(labels)
@settings(max_examples=12, deadline=None)
def test_tombstone_convergence_is_order_independent(values: list[str]) -> None:
    root = Path(tempfile.mkdtemp())
    remote = MemoryBackend()
    first = Repository(root / "a" / "history.sqlite3")
    second = Repository(root / "b" / "history.sqlite3")
    unique = list(dict.fromkeys(values))
    for index, text in enumerate(unique, start=1):
        first.create_local_clip(
            text,
            device_id="a",
            device_name="A",
            max_bytes=1024,
            history_limit=120,
            captured_at=datetime(2026, 8, 16, second=index, tzinfo=UTC),
        )
    _engine(first, remote).sync(PASSPHRASE)
    _engine(second, remote).sync(PASSPHRASE)
    target = unique[0]
    item = next(row for row in first.list_history(limit=None) if row.record.text == target)
    first.create_tombstones([item.record.id], device_id="a", device_name="A")
    _engine(first, remote).sync(PASSPHRASE)
    _engine(second, remote).sync(PASSPHRASE)
    assert target not in {row.record.text for row in first.list_history(limit=None)}
    assert target not in {row.record.text for row in second.list_history(limit=None)}
