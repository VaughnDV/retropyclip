UV ?= uv

.PHONY: check test package audit demo sbom upgrade

check:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy

test:
	$(UV) run pytest

package:
	$(UV) build
	bash scripts/packaging-smoke.sh

audit:
	$(UV) run python scripts/audit.py

demo:
	bash scripts/safe-demo.sh

sbom:
	$(UV) run python scripts/sbom.py

upgrade:
	$(UV) lock --upgrade
	@echo "Review uv.lock, then run: $(UV) run pytest"
