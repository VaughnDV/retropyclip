#!/usr/bin/env bash
# Safe portfolio demonstration. Synthetic text only. Isolated RETROPYCLIP_HOME.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
export RETROPYCLIP_HOME="${RETROPYCLIP_HOME:-$root/tmp/demo-home}"
rm -rf "$RETROPYCLIP_HOME"
mkdir -p "$RETROPYCLIP_HOME"

echo "== Isolated home: $RETROPYCLIP_HOME"
uv run retropyclip add "demo: sprint standup notes"
uv run retropyclip add "demo: grocery list"
uv run retropyclip add "demo: ssh host nickname"
uv run retropyclip history --json

echo
echo "== Encrypted local records without OAuth"
uv run python - <<'PY'
from datetime import UTC, datetime
from pathlib import Path
import os

from retropyclip.crypto.envelope import KDFParameters
from retropyclip.storage.sqlite import Repository
from retropyclip.sync.backend import MemoryBackend
from retropyclip.sync.engine import SyncEngine

home = Path(os.environ["RETROPYCLIP_HOME"])
passphrase = "demo-only-passphrase"
fast = KDFParameters(time_cost=1, memory_cost_kib=32, parallelism=1)
remote = MemoryBackend()

def repo(name: str) -> Repository:
    return Repository(home / name / "history.sqlite3")

def engine(repository: Repository) -> SyncEngine:
    return SyncEngine(
        repository, remote, max_item_bytes=65_536, history_limit=120,
        sleeper=lambda _: None, kdf_parameters=fast,
    )

alpha = repo("alpha")
beta = repo("beta")
alpha.create_local_clip(
    "demo: offline alpha clip",
    device_id="alpha", device_name="Alpha",
    max_bytes=1024, history_limit=120,
    captured_at=datetime(2026, 8, 16, 10, tzinfo=UTC),
)
engine(alpha).sync(passphrase)
print("alpha uploaded encrypted records:", len(remote.list_objects()))

tampered = b'{"schema":"retropyclip.record/1","id":"nope","kind":"clip","nonce":"AAAAAAAAAAAA","ciphertext":"AAAA"}'
remote.upload("tampered.rpc.json", tampered)
report = engine(alpha).pull(passphrase)
print("tampered record rejected:", bool(report.errors))

beta.create_local_clip(
    "demo: offline beta clip",
    device_id="beta", device_name="Beta",
    max_bytes=1024, history_limit=120,
    captured_at=datetime(2026, 8, 16, 11, tzinfo=UTC),
)
engine(beta).sync(passphrase)
engine(alpha).sync(passphrase)
print("alpha history after convergence:")
for item in alpha.list_history(limit=None):
    print(" -", item.record.text)
PY

echo
echo "Demo complete. No real OAuth, no real clipboard secrets."
