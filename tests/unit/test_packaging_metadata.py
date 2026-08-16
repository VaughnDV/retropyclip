from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gui_extra_is_not_a_core_dependency() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    core = " ".join(data["project"]["dependencies"])
    assert "PySide6" not in core
    assert "pyinstaller" not in core.lower()
    extras = data["project"]["optional-dependencies"]
    assert any("PySide6" in item for item in extras["gui"])
    assert any("pyinstaller" in item.lower() for item in extras["build"])
