from __future__ import annotations

import getpass
import json
import os
import platform
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

import typer

from retropyclip import __version__
from retropyclip.config import MAX_CONFIGURABLE_ITEM_BYTES
from retropyclip.core.models import SyncReport, format_utc
from retropyclip.core.text import InvalidClip, one_line_preview
from retropyclip.crypto.diagnostics import sanitize_diagnostic
from retropyclip.crypto.envelope import CryptoError, InvalidPassphrase
from retropyclip.platforms.clipboard import (
    ClipboardMonitor,
    ClipboardUnavailable,
    capabilities,
    detect_clipboard,
)
from retropyclip.runtime import Runtime
from retropyclip.sync.auth import install_client_secrets, login_browser, login_device
from retropyclip.sync.backend import AuthenticationRequired, BackendError
from retropyclip.sync.engine import SyncDisabled

app = typer.Typer(
    name="retropyclip",
    help="Private-first, encrypted text clipboard history.",
    no_args_is_help=True,
    rich_markup_mode=None,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"RetroPyClip {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """Store clipboard history locally and sync encrypted text through your Drive."""


def _runtime() -> Runtime:
    try:
        return Runtime.open()
    except RuntimeError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from error


def _passphrase(runtime: Runtime) -> str:
    environment = os.environ.get("RETROPYCLIP_SYNC_PASSPHRASE")
    if environment is not None:
        return environment
    first = getpass.getpass("Sync passphrase: ")
    if runtime.repository.get_meta("keyinfo") is None:
        second = getpass.getpass("Confirm sync passphrase: ")
        if first != second:
            raise InvalidPassphrase("sync passphrases do not match")
    return first


def _perform_sync(action: Literal["push", "pull", "sync"]) -> SyncReport:
    runtime = _runtime()
    try:
        engine = runtime.sync_engine()
        passphrase = _passphrase(runtime)
        if action == "push":
            return engine.push(passphrase)
        if action == "pull":
            return engine.pull(passphrase)
        return engine.sync(passphrase)
    except (AuthenticationRequired, BackendError, CryptoError, SyncDisabled) as error:
        typer.echo(f"Sync failed: {sanitize_diagnostic(str(error))}", err=True)
        raise typer.Exit(1) from error


def _print_report(report: SyncReport) -> None:
    typer.echo(
        f"Pulled {report.pulled}, pushed {report.pushed}, skipped {report.skipped}, "
        f"rejected {len(report.errors)}."
    )


@app.command()
def login(
    client_secrets: Annotated[
        Path | None,
        typer.Option(
            "--client-secrets",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Downloaded Google OAuth client JSON.",
        ),
    ] = None,
    headless: Annotated[
        bool, typer.Option("--headless", help="Use Google's limited-input device flow.")
    ] = False,
) -> None:
    """Connect this device to a Google account using the narrow app-data scope."""
    runtime = _runtime()
    supplied = client_secrets or (
        Path(os.environ["RETROPYCLIP_GOOGLE_CLIENT_SECRETS"])
        if os.environ.get("RETROPYCLIP_GOOGLE_CLIENT_SECRETS")
        else None
    )
    try:
        if supplied:
            client_file = install_client_secrets(supplied, runtime.paths)
        elif runtime.paths.client_secrets_file.exists():
            client_file = runtime.paths.client_secrets_file
        else:
            typer.echo(
                "A Google OAuth client JSON is required. See docs/google-oauth-setup.md.",
                err=True,
            )
            raise typer.Exit(2)
        if headless:
            login_device(
                client_file,
                runtime.credentials,
                display=lambda url, code: typer.echo(
                    f"Open {url} on another device and enter code: {code}"
                ),
            )
        else:
            login_browser(client_file, runtime.credentials)
    except (AuthenticationRequired, BackendError, FileNotFoundError, ValueError) as error:
        typer.echo(f"Login failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo("Google account connected. Clipboard text has not been uploaded yet.")


@app.command()
def logout() -> None:
    """Remove this device's stored Google authorization."""
    runtime = _runtime()
    runtime.credentials.delete()
    typer.echo("Google authorization removed from this device. Remote data was not deleted.")


@app.command()
def status() -> None:
    """Show local, capture, and synchronization state without revealing clip text."""
    runtime = _runtime()
    stats = runtime.repository.stats()
    sync_state = runtime.sync_status()
    auth = "connected" if runtime.credentials.present() else "login required"
    pause = "active" if runtime.capture_enabled() else "paused"
    typer.echo(f"Device: {runtime.settings.device_name} ({runtime.settings.device_id})")
    typer.echo(f"Capture: {pause}")
    typer.echo(f"Google: {auth}")
    typer.echo(f"Mode: {'local only' if runtime.settings.local_only else 'sync enabled'}")
    typer.echo(
        f"History: {stats['active']} active / {runtime.settings.history_limit} limit; "
        f"{stats['pending']} pending"
    )
    if sync_state:
        typer.echo(
            f"Last sync state: {str(sync_state.get('state', 'unknown')).replace('_', ' ')} "
            f"at {sync_state.get('updated_at', 'unknown')}"
        )
    else:
        typer.echo("Last sync state: never synchronized")


@app.command()
def add(
    text: Annotated[str | None, typer.Argument(help="Text to add; omit to read standard input.")] = None,
) -> None:
    """Add plain text directly, or read it exactly from standard input."""
    runtime = _runtime()
    if text is None:
        if sys.stdin.isatty():
            typer.echo("Provide TEXT or pipe text on standard input.", err=True)
            raise typer.Exit(2)
        text = sys.stdin.read()
    try:
        item, created = runtime.repository.create_local_clip(
            text,
            device_id=runtime.settings.device_id,
            device_name=runtime.settings.device_name,
            max_bytes=runtime.settings.max_item_bytes,
            history_limit=runtime.settings.history_limit,
        )
    except InvalidClip as error:
        typer.echo(f"Not added: {error}", err=True)
        raise typer.Exit(1) from error
    if created and item:
        typer.echo(item.record.id)
    else:
        typer.echo("Duplicate suppressed.")


@app.command()
def history(
    limit: Annotated[int, typer.Option("--limit", min=1, max=100_000)] = 30,
    as_json: Annotated[bool, typer.Option("--json", help="Print metadata as JSON.")] = False,
) -> None:
    """List the newest active clipboard items without printing full contents."""
    items = _runtime().repository.list_history(limit=limit)
    if as_json:
        payload = [
            {
                "id": item.record.id,
                "preview": one_line_preview(item.record.text or ""),
                "captured_at": format_utc(item.record.captured_at),
                "device": item.record.device_name,
                "sync_state": item.sync_state.value,
            }
            for item in items
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not items:
        typer.echo("History is empty.")
        return
    for item in items:
        record = item.record
        timestamp = record.captured_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        typer.echo(
            f"{record.id}  {timestamp}  {record.device_name}  "
            f"[{item.sync_state.value}]  {one_line_preview(record.text or '')}"
        )


def _resolve_item(runtime: Runtime, item_id: str):  # type: ignore[no-untyped-def]
    try:
        item = runtime.repository.resolve(item_id)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(2) from error
    if item is None:
        typer.echo("No active history item matches that ID.", err=True)
        raise typer.Exit(1)
    return item


@app.command()
def show(item_id: Annotated[str, typer.Argument(help="Full item ID or unique prefix.")]) -> None:
    """Write one item's exact text to standard output."""
    item = _resolve_item(_runtime(), item_id)
    typer.echo(item.record.text or "", nl=False)


@app.command()
def copy(item_id: Annotated[str, typer.Argument(help="Full item ID or unique prefix.")]) -> None:
    """Put one item on the system clipboard as plain text."""
    runtime = _runtime()
    item = _resolve_item(runtime, item_id)
    text = item.record.text or ""
    try:
        adapter = detect_clipboard()
        runtime.repository.set_clipboard_suppression(text)
        adapter.set_text(text)
    except ClipboardUnavailable as error:
        typer.echo(f"Copy failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo("Copied as plain text.")


@app.command()
def push() -> None:
    """Encrypt and upload unsynchronized local records."""
    _print_report(_perform_sync("push"))


@app.command()
def pull() -> None:
    """Download and merge unseen remote records without changing the clipboard."""
    _print_report(_perform_sync("pull"))


@app.command()
def sync() -> None:
    """Pull unseen records, then push pending local records."""
    _print_report(_perform_sync("sync"))


@app.command()
def pause(
    minutes: Annotated[
        int | None,
        typer.Option("--minutes", min=1, max=7 * 24 * 60, help="Resume capture automatically."),
    ] = None,
    sync_only: Annotated[
        bool, typer.Option("--sync", help="Pause synchronization instead of capture.")
    ] = False,
) -> None:
    """Pause capture persistently or for a bounded time; optionally pause sync."""
    runtime = _runtime()
    if sync_only:
        runtime.settings.sync_paused = True
        runtime.config.save(runtime.settings)
        typer.echo("Synchronization paused.")
        return
    runtime.settings.capture_paused = True
    runtime.settings.pause_until = (
        format_utc(datetime.now(UTC) + timedelta(minutes=minutes)) if minutes else None
    )
    runtime.config.save(runtime.settings)
    typer.echo(f"Capture paused for {minutes} minutes." if minutes else "Capture paused.")


@app.command()
def resume(
    sync_only: Annotated[
        bool, typer.Option("--sync", help="Resume synchronization instead of capture.")
    ] = False,
) -> None:
    """Resume clipboard capture or synchronization."""
    runtime = _runtime()
    if sync_only:
        runtime.settings.sync_paused = False
        runtime.config.save(runtime.settings)
        typer.echo("Synchronization resumed.")
        return
    runtime.settings.capture_paused = False
    runtime.settings.pause_until = None
    runtime.config.save(runtime.settings)
    typer.echo("Capture resumed.")


@app.command("clear-local")
def clear_local(
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Hide local history without deleting records on other devices."""
    if not yes and not typer.confirm("Clear active history on this device?"):
        raise typer.Abort()
    count = _runtime().repository.clear_local()
    typer.echo(f"Cleared {count} local item(s). Remote records were not changed.")


@app.command("clear-everywhere")
def clear_everywhere(
    confirmation: Annotated[
        str | None,
        typer.Option("--confirm", help="Pass exactly CLEAR EVERYWHERE for non-interactive use."),
    ] = None,
) -> None:
    """Queue encrypted tombstones for every active history item."""
    phrase = confirmation or typer.prompt("Type CLEAR EVERYWHERE to queue global deletion")
    if phrase != "CLEAR EVERYWHERE":
        typer.echo("Confirmation did not match; nothing was changed.", err=True)
        raise typer.Exit(2)
    runtime = _runtime()
    count = runtime.repository.clear_everywhere(
        device_id=runtime.settings.device_id,
        device_name=runtime.settings.device_name,
    )
    runtime.settings.capture_paused = True
    runtime.settings.pause_until = None
    runtime.config.save(runtime.settings)
    typer.echo(
        f"Queued {count} tombstone(s). Capture is paused so leftover clipboard "
        "text is not recaptured. Run 'retropyclip resume', then 'retropyclip sync' "
        "on every device."
    )


@app.command("export")
def export_history(
    output: Annotated[Path, typer.Argument(help="New recovery export path.")],
    format: Annotated[Literal["json", "text"], typer.Option("--format")] = "json",
) -> None:
    """Explicitly export active history to plaintext JSON or form-feed-separated text."""
    if output.exists():
        typer.echo("Refusing to overwrite an existing export file.", err=True)
        raise typer.Exit(2)
    repository = _runtime().repository
    data = (
        repository.export_json()
        if format == "json"
        else "\n\f\n".join(
            item.record.text or "" for item in reversed(repository.list_history(limit=None))
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(data, "utf-8")
    os.chmod(output, 0o600)
    typer.echo(f"Exported plaintext history to {output}.")


@app.command("import")
def import_history(
    source: Annotated[
        Path, typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True)
    ],
    format: Annotated[Literal["auto", "json", "text"], typer.Option("--format")] = "auto",
) -> None:
    """Import a RetroPyClip JSON export or form-feed-separated plaintext history."""
    runtime = _runtime()
    raw = source.read_text("utf-8")
    selected = "json" if format == "auto" and raw.lstrip().startswith("{") else format
    if selected == "auto":
        selected = "text"
    try:
        if selected == "json":
            payload = json.loads(raw)
            if payload.get("schema") != "retropyclip.export/1":
                raise ValueError("unsupported export schema")
            texts = [str(item["text"]) for item in payload.get("clips", [])]
        else:
            texts = raw.split("\n\f\n")
        created = 0
        for text in texts:
            _, added = runtime.repository.create_local_clip(
                text,
                device_id=runtime.settings.device_id,
                device_name=runtime.settings.device_name,
                max_bytes=runtime.settings.max_item_bytes,
                history_limit=runtime.settings.history_limit,
            )
            created += int(added)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidClip) as error:
        typer.echo(f"Import failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"Imported {created} item(s).")


@app.command()
def doctor() -> None:
    """Check platform capabilities and private local storage without reading clip text."""
    runtime = _runtime()
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python", sys.version_info >= (3, 12), platform.python_version()))
    checks.append(("Database", runtime.paths.database_file.exists(), str(runtime.paths.database_file)))
    checks.append(
        (
            "Database permissions",
            not bool(runtime.paths.database_file.stat().st_mode & 0o077),
            oct(runtime.paths.database_file.stat().st_mode & 0o777),
        )
    )
    for label, path in (
        ("Config directory", runtime.paths.config_dir),
        ("Data directory", runtime.paths.data_dir),
    ):
        mode = path.stat().st_mode & 0o777
        checks.append((f"{label} permissions", not bool(mode & 0o077), oct(mode)))
    if runtime.paths.token_file.exists():
        mode = runtime.paths.token_file.stat().st_mode & 0o777
        checks.append(("Token fallback permissions", not bool(mode & 0o077), oct(mode)))
    caps = capabilities()
    desktop_expected = caps.session != "headless"
    checks.append(
        (
            "Clipboard",
            caps.can_read and caps.can_write if desktop_expected else True,
            f"{caps.session}: {caps.adapter}",
        )
    )
    checks.append(
        (
            "Concealed markers",
            True,
            "supported" if caps.concealed_markers else "not exposed by this adapter",
        )
    )
    checks.append(
        ("Google OAuth", runtime.credentials.present(), "connected" if runtime.credentials.present() else "login required")
    )
    for label, passed, detail in checks:
        typer.echo(f"{'OK' if passed else 'WARN':4}  {label}: {detail}")
    if not all(passed for label, passed, _ in checks if label != "Google OAuth"):
        raise typer.Exit(1)


@app.command()
def daemon() -> None:
    """Watch a desktop clipboard and save text changes until interrupted."""
    runtime = _runtime()
    try:
        adapter = detect_clipboard()
        if adapter.name == "headless":
            raise ClipboardUnavailable("no desktop clipboard is available in this session")
    except ClipboardUnavailable as error:
        typer.echo(f"Daemon cannot start: {error}", err=True)
        raise typer.Exit(1) from error

    def capture(text: str) -> None:
        settings = runtime.reload_settings()
        try:
            item, created = runtime.repository.create_local_clip(
                text,
                device_id=settings.device_id,
                device_name=settings.device_name,
                max_bytes=settings.max_item_bytes,
                history_limit=settings.history_limit,
            )
            if created and item:
                typer.echo(f"Captured {item.record.id}")
        except InvalidClip:
            return

    monitor = ClipboardMonitor(
        adapter,
        capture,
        should_capture=runtime.capture_enabled,
        interval=runtime.settings.clipboard_poll_seconds,
    )
    typer.echo(f"Watching {adapter.name}; press Ctrl+C to stop.")
    try:
        monitor.run()
    except KeyboardInterrupt:
        monitor.stop()
        typer.echo("\nStopped.")


@app.command()
def configure(
    device_name: Annotated[str | None, typer.Option("--device-name")] = None,
    history_limit: Annotated[int | None, typer.Option("--history-limit", min=1, max=100_000)] = None,
    max_item_bytes: Annotated[
        int | None,
        typer.Option("--max-item-bytes", min=1, max=MAX_CONFIGURABLE_ITEM_BYTES),
    ] = None,
    local_only: Annotated[bool | None, typer.Option("--local-only/--allow-sync")] = None,
) -> None:
    """Update safe local settings; omitted options are unchanged."""
    runtime = _runtime()
    if device_name is not None:
        runtime.settings.device_name = device_name.strip()
    if history_limit is not None:
        runtime.settings.history_limit = history_limit
    if max_item_bytes is not None:
        runtime.settings.max_item_bytes = max_item_bytes
    if local_only is not None:
        runtime.settings.local_only = local_only
    try:
        runtime.config.save(runtime.settings)
        runtime.repository.enforce_retention(runtime.settings.history_limit)
    except ValueError as error:
        typer.echo(f"Configuration rejected: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo("Configuration updated.")
