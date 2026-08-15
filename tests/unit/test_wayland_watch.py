from __future__ import annotations

from io import BytesIO

from retropyclip.platforms.clipboard import WaylandClipboardWatcher
from retropyclip.platforms.wayland_watch_frame import encode_frame


def test_wayland_watcher_preserves_event_boundaries() -> None:
    watcher = WaylandClipboardWatcher()
    stream = BytesIO(
        encode_frame(b"first clipboard value")
        + encode_frame(b"second\nclipboard value")
    )

    watcher._consume(stream)

    assert watcher.take_pending() == [
        "first clipboard value",
        "second\nclipboard value",
    ]
    assert watcher.take_pending() == []
