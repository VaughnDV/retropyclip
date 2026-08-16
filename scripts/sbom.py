"""Write a minimal CycloneDX SBOM from uv.lock for release artifacts."""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text("utf-8"))
    components = []
    for package in lock.get("package", []):
        name = str(package.get("name", ""))
        version = str(package.get("version", ""))
        if not name or not version:
            continue
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
            }
        )
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {"type": "application", "name": "retropyclip", "version": "0.1.0"},
        },
        "components": components,
    }
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / "sbom.cdx.json"
    path.write_text(json.dumps(document, indent=2) + "\n", "utf-8")
    print(path)


if __name__ == "__main__":
    main()
