from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from retropyclip.core.text import InvalidClip, validate_text
from retropyclip.platforms.clipboard import ClipboardMonitor
from retropyclip.storage.sqlite import Repository


def test_nul_and_oversize_and_empty_are_rejected() -> None:
    with pytest.raises(InvalidClip, match="NUL"):
        validate_text("ok\x00secret", 1024)
    with pytest.raises(InvalidClip, match="empty"):
        validate_text("", 1024)
    with pytest.raises(InvalidClip, match="limit"):
        validate_text("x" * 50, 16)


def test_unicode_text_is_preserved(repository: Repository) -> None:
    item, created = repository.create_local_clip(
        "café 📋 \u2028 line",
        device_id="device",
        device_name="Mac",
        max_bytes=4096,
        history_limit=20,
    )
    assert created is True
    assert item is not None
    assert item.record.text == "café 📋 \u2028 line"


def test_rapid_churn_respects_retention(repository: Repository) -> None:
    base = datetime(2026, 8, 16, tzinfo=UTC)
    for index in range(30):
        repository.create_local_clip(
            f"burst-{index}",
            device_id="device",
            device_name="Mac",
            max_bytes=1024,
            history_limit=5,
            captured_at=base + timedelta(seconds=index),
        )
    texts = [item.record.text for item in repository.list_history(limit=None)]
    assert texts == [f"burst-{index}" for index in range(29, 24, -1)]


def test_monitor_does_not_capture_while_paused() -> None:
    class FakeAdapter:
        name = "fake"

        @staticmethod
        def read_text() -> str:
            return "should-not-store"

        @staticmethod
        def is_concealed() -> bool:
            return False

    captured: list[str] = []
    monitor = ClipboardMonitor(
        FakeAdapter(),  # type: ignore[arg-type]
        captured.append,
        should_capture=lambda: False,
        interval=0.01,
    )
    thread = threading.Thread(target=monitor.run)
    thread.start()
    time.sleep(0.05)
    monitor.stop()
    thread.join(timeout=1)
    assert captured == []
