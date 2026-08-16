# Clipboard behaviour and desktop permissions

## Copying an old item

Copying a history item (`retropyclip copy`, tray History, or the macOS popup)
places the exact stored text on the system clipboard and writes a one-shot
suppression hash. The next capture of that same text is ignored.

That recapture **does not** create a duplicate row and **does not** reset
retention. The original `captured_at` timestamp stays. Copying is "put this text
back on the clipboard", not "touch the history row".

If a different clip is captured in between, a later copy of the same text is a
new event, matching ordinary clipboard history.

## Pause, resume, and process restart

`capture_paused` and optional `pause_until` are stored in `settings.json`. A
daemon or tray restart reloads them, so a pause survives process death. While
capture is paused, the daemon, tray Qt listener, Wayland watcher, and GNOME
bridge callback all refuse to insert rows.

`sync_paused` and `local_only` make `SyncEngine` raise `SyncDisabled` before any
network call. The tray disables Sync Now in those states.

## Clear everywhere

`clear-everywhere` queues encrypted tombstones for every active row, then pauses
capture so leftover clipboard text is not immediately recaptured and queued for
upload. Sync remains available so tombstones can be pushed. Run `retropyclip resume`
when you want capture again, then sync every other device.

## GNOME session-bus bridge

The bridge registers `io.github.VaughnDV.RetroPyClip` on the **session** bus only.
A session bus is already scoped to the logged-in user. Other users and other
machines cannot call `CaptureText`. A process running as the same user can; that
is inside the local-endpoint threat model. Oversized, empty, and NUL-containing
payloads are ignored.

## Global shortcut and Accessibility

| Build | Shortcut | Extra permission |
|---|---|---|
| macOS development (`uv run retropyclip-tray`) | `Cmd+Shift+V` via Carbon | None for the shortcut itself. macOS may list the **terminal or Python** as the owning app. |
| macOS packaged app (future signed `.app`) | Same Carbon registration | None for the shortcut. The `.app` bundle name appears in System Settings. |
| macOS automatic paste after picking an item | Synthetic `Cmd+V` | **Accessibility** for the same process that registered the hotkey. Enable System Settings → Privacy & Security → Accessibility. |
| Linux (current) | No global shortcut | Tray menu and CLI only. A desktop-wide shortcut is not claimed. |

If Accessibility is denied, the selected item is still copied as plain text so
`Cmd+V` remains a fallback. RetroPyClip never requests Full Disk Access or
screen-recording permission.
