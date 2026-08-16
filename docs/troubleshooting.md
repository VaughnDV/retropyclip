# Troubleshooting

## Permissions

- **macOS Accessibility:** automatic paste after `Cmd+Shift+V` needs Accessibility
  for the process that launched the tray (the `.app`, or Python/the terminal in
  development). The shortcut itself does not. See [desktop-permissions.md](desktop-permissions.md).
- **Database mode:** `retropyclip doctor` should report `0600`. If it does not,
  another tool created the data directory too openly; RetroPyClip will tighten it
  on the next start.

## Keyring fallback

If the OS keyring is unavailable, OAuth tokens are stored in
`google-token.json` mode `0600` under the config directory. Isolated
`RETROPYCLIP_HOME` demos use a path-scoped keyring account and will not see your
real login.

## OAuth

- Confirm the client is a Desktop app and the scope is only `drive.appdata`.
- Testing-mode Google Cloud projects expire refresh tokens after seven days.
- `login required` after a revoke is expected; run `retropyclip login` again.
- Never commit `client_secret*.json`.

## Linux clipboard backends

- **X11:** install `xclip` or `xsel`.
- **Sway/Hyprland:** install `wl-clipboard`. Watching uses `wl-paste --watch`.
- **Ubuntu GNOME Wayland:** install the bundled session-bus extension via
  `ubuntu-update.sh`, then log out and back in once.
- **Headless:** `add`, `show`, `push`, and `pull` work without a clipboard.

## Sync paused after clear everywhere

Capture is paused so leftover clipboard text is not recaptured. Run
`retropyclip resume`, then `retropyclip sync` on every device.
