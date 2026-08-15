# Real-device feasibility checklist

Run this checklist before relying on cloud sync or investing in release packaging.
It records the Stage 0 work that cannot be proven in an isolated development build.
Use synthetic clipboard text throughout.

## 1. macOS

```bash
uv sync --all-extras
uv run retropyclip doctor
uv run retropyclip daemon
```

Copy a synthetic multiline value, confirm it appears in `retropyclip history`, select
it with `retropyclip copy ITEM_ID`, and verify the line endings and surrounding spaces
with `retropyclip show ITEM_ID`. Confirm concealed items from your password manager
are ignored when its native marker is exposed. Do not test with a real password.

## 2. Ubuntu

Run `echo "$XDG_SESSION_TYPE"` to record X11 or Wayland, then repeat the capture and
copy test. On X11 install `xclip` or `xsel`. On Wayland install `wl-clipboard` and
record compositor-specific limitations. A tray may be unavailable unless the desktop
provides a status-notifier host.

## 3. Raspberry Pi / ARM64

In desktop mode repeat the Ubuntu test. In a truly headless session, `doctor` should
report headless without treating the missing clipboard as a failure:

```bash
printf 'synthetic Pi clip' | retropyclip add
retropyclip history
retropyclip show ITEM_ID
```

## 4. One-account Drive round trip

Follow [google-oauth-setup.md](google-oauth-setup.md). Establish the sync passphrase
on one device first, then connect the others with the same passphrase.

1. Add one uniquely labelled synthetic clip on each device while offline.
2. Sync Mac, Ubuntu, and Pi in that order.
3. Sync all three again and confirm all three labels exist everywhere.
4. Confirm no pull changed any device's active clipboard.
5. Queue `clear-everywhere` on one device, sync all devices, and confirm no clip
   reappears after the previously offline device reconnects.

Record results, OS versions, desktop session, CPU architecture, Python version, and
OAuth client type. A failure here is a go/no-go result; fix it before signing or
notarising a GUI build.
