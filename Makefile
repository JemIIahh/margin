.PHONY: test lint
test:
	uv run pytest
lint:
	uv run ruff check src tests

.PHONY: verify
verify:
	uv run pytest
	uv run margin report --check
