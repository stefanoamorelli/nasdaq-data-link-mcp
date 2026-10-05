## What and why

<!-- What does this change, and why is it needed? Link the issue if there is one. -->

## Type of change

- [ ] Bug fix
- [ ] New tool, toolset or catalog update
- [ ] Breaking change (tool names, parameters, output shape or settings)
- [ ] Documentation
- [ ] CI, packaging or Docker
- [ ] Refactoring (no behaviour change)

## Checks

- [ ] `uv run pytest` passes (offline tests, no API key needed)
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy nasdaq_data_link_mcp_os` passes
- [ ] New or changed tools have offline tests (`tests/test_<toolset>.py`)
- [ ] Live tests run with a real key, if the change touches API calls (`uv run pytest -m live`)
- [ ] CHANGELOG.md updated for user-visible changes

## Notes for reviewers

<!-- Data caveats, access levels (free / sample / subscription), anything you could not test. -->
