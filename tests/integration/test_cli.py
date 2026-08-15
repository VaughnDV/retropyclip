from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from retropyclip.cli import app

runner = CliRunner()


def test_local_cli_workflow(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    home = tmp_path / "home"
    monkeypatch.setenv("RETROPYCLIP_HOME", str(home))

    added = runner.invoke(app, ["add", "  exact text  "])
    assert added.exit_code == 0, added.output
    item_id = added.output.strip()

    listed = runner.invoke(app, ["history", "--json"])
    assert listed.exit_code == 0, listed.output
    payload = json.loads(listed.output)
    assert payload[0]["id"] == item_id
    assert payload[0]["preview"] == "exact text"

    shown = runner.invoke(app, ["show", item_id[:10]])
    assert shown.exit_code == 0
    assert shown.output == "  exact text  "


def test_pipe_add_and_duplicate_suppression(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RETROPYCLIP_HOME", str(tmp_path / "home"))
    first = runner.invoke(app, ["add"], input="piped\r\ntext")
    second = runner.invoke(app, ["add"], input="piped\ntext")
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Duplicate suppressed" in second.output


def test_export_import_recovery(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    first_home = tmp_path / "first"
    monkeypatch.setenv("RETROPYCLIP_HOME", str(first_home))
    runner.invoke(app, ["add", "one"])
    runner.invoke(app, ["add", "two"])
    recovery = tmp_path / "recovery.json"
    exported = runner.invoke(app, ["export", str(recovery)])
    assert exported.exit_code == 0, exported.output
    assert recovery.stat().st_mode & 0o077 == 0

    monkeypatch.setenv("RETROPYCLIP_HOME", str(tmp_path / "second"))
    imported = runner.invoke(app, ["import", str(recovery)])
    assert imported.exit_code == 0, imported.output
    listed = runner.invoke(app, ["history", "--json"])
    assert {row["preview"] for row in json.loads(listed.output)} == {"one", "two"}


def test_pause_and_resume(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RETROPYCLIP_HOME", str(tmp_path / "home"))
    assert runner.invoke(app, ["pause", "--minutes", "5"]).exit_code == 0
    assert runner.invoke(app, ["resume"]).exit_code == 0
