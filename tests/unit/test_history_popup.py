from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from retropyclip.core.models import Record, RecordKind, StoredRecord, SyncState, uuid7
from retropyclip.ui.history_popup import HistoryPopup


def _record(text: str) -> StoredRecord:
    return StoredRecord(
        record=Record(
            id=uuid7(),
            kind=RecordKind.CLIP,
            captured_at=datetime(2026, 8, 16, 12, tzinfo=UTC),
            device_id="ui",
            device_name="UI",
            sequence=1,
            text=text,
        ),
        sync_state=SyncState.PENDING,
        origin="local",
        remote_file_id=None,
        deleted_at=None,
    )


@pytest.mark.desktop
def test_history_popup_filters_and_selects_without_a_display() -> None:
    application = QApplication.instance() or QApplication([])
    selected: list[str] = []
    popup = HistoryPopup(selected.append)
    popup.set_records([_record("alpha clip"), _record("beta note")])
    assert popup.list.count() == 2
    popup.search.setText("beta")
    visible = [not popup.list.item(row).isHidden() for row in range(popup.list.count())]
    assert visible.count(True) == 1
    current = popup.list.currentItem()
    assert current is not None
    popup._activate_item(current)
    assert selected == ["beta note"]
    popup.close()
    del application
