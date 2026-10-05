# Contributing

Thanks for helping. This file covers the development setup, the checks a
change has to pass, and how to add a toolset. By contributing you agree that
your contribution is licensed under the project's [MIT License](LICENSE).

## Setup

You need Python 3.11 or newer, [uv](https://docs.astral.sh/uv/) and git.

```bash
git clone https://github.com/stefanoamorelli/nasdaq-data-link-mcp.git
cd nasdaq-data-link-mcp
uv sync                     # creates .venv with runtime and dev dependencies
uv run pre-commit install   # ruff and file checks before every commit
uv run nasdaq-data-link-mcp --version
```

For the live tests and for trying the server in a client, get a free API key
at <https://data.nasdaq.com/sign-up> and export it as
`NASDAQ_DATA_LINK_API_KEY`, or put it in a `.env` file in the repository root
(git ignores `.env`; see `.env.example`).

## Checks

Every pull request runs these in CI; run them before pushing:

```bash
uv run pytest                                  # offline tests
uv run ruff check . && uv run ruff format --check .
uv run mypy nasdaq_data_link_mcp_os scripts
uv run python scripts/generate_tool_docs.py --check
```

- **Offline tests** (`tests/`) run every tool against `tests/fake_nasdaq.py`,
  a fake of the Tables API and DataLink SQL, through a real MCP client. They
  need no key and no network. `uv run pytest --cov` adds coverage.
- **Live tests** (`tests/live/`, marker `live`) call the real API and are
  deselected by default. Run them with `uv run pytest -m live`, or one file
  with `uv run pytest -m live tests/live/test_live_crypto.py`. They need
  `NASDAQ_DATA_LINK_API_KEY`; a free key is enough, and the whole suite makes
  a little under 200 calls. A free key allows one request at a time, so run
  them alone. Run them when a change touches API calls, and say in the pull
  request if you could not.
- **Style:** ruff with the rules in `pyproject.toml` (line length 88) and
  ruff's formatter; mypy must pass. Prefer clear names over comments, and
  comments that say why over comments that say what.
- **Generated docs:** the tool tables in `README.md` and the pages under
  `docs/tools/` are written by `scripts/generate_tool_docs.py`. After changing
  a tool, a prompt, a resource or the catalog, run it without `--check` and
  commit the result. Do not edit the generated parts by hand.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org)
(`feat(crypto): ...`, `fix(security): ...`, `docs: ...`; `!` marks a breaking
change), and commits should be signed; see [SECURITY.md](SECURITY.md). Add an
entry to the unreleased version at the top of [CHANGELOG.md](CHANGELOG.md) for
any change users can see.

## Writing tools

Tools are read by a model, not a person, so:

- The first line of the docstring says what the tool returns, in under about
  80 characters; it becomes the summary in the README and the docs.
- The rest names the tables it reads, what a free key gets (free, sample,
  subscription), where the data ends if Nasdaq stopped updating it, and the
  row order. Keep it short: every enabled tool's description is sent to the
  model on every request.
- Use the shared parameter names and types from
  `nasdaq_data_link_mcp_os/tools/_common.py` (`tickers`, `start_date`,
  `end_date`, `limit`, ...). Every parameter needs a description; unknown
  arguments are rejected.
- Return rows in a useful order (usually newest first) and put caveats in
  `notes`. Errors raised as `NdlError` subclasses reach the model with a label
  such as `[INVALID_REQUEST]`.
- Tools are read-only. A tool that never calls Nasdaq is marked `local=True`.

## Adding a toolset

1. **Module.** Create `nasdaq_data_link_mcp_os/tools/<name>.py`. Tools are
   plain functions named `ndl_<verb>_<object>`; a tool that calls the API is
   `async` and takes `ctx: Context` first. Read rows with `fetch_table`, or
   with `read_table` plus `build_result` when the tool filters or ranks rows
   itself, and return `to_tool_result(...)` with a pydantic output model
   (`-> Annotated[CallToolResult, YourModel]`) so the tool has an output
   schema.
2. **Toolset.** At the end of the module, declare it:

   ```python
   TOOLSET = Toolset(
       name="<name>",
       description="One line on what the toolset covers.",
       tools=(
           ToolSpec(ndl_get_example, "Get example data", tables=("VENDOR/TABLE",)),
       ),
       prompts=(PromptSpec(example_prompt, "Example prompt"),),  # optional
   )
   ```

   `tables=` lists every table the tool reads. It is how `ndl_search_tables`
   and `ndl_describe_table` point to the tool, and how the generated docs work
   out what a free key gets.
3. **Registration.** Import the module in
   `nasdaq_data_link_mcp_os/tools/__init__.py` and add it to the tuple that
   builds `TOOLSETS`; the order there is the order of the docs.
4. **Catalog.** Add each table the toolset reads to
   `nasdaq_data_link_mcp_os/data/catalog.json`: code, vendor, a name and a
   description of at most 120 characters in your own words, the access level,
   optional notes, filters, primary key and docs URL. Never copy text from
   Nasdaq or vendor pages and never list values from sample data (tickers,
   ISINs, row counts); the catalog tests reject both. Check the access level
   and schema with `uv run python scripts/refresh_catalog.py --only
   VENDOR/TABLE --dry-run` (needs a free key).
5. **Offline tests.** Add `tests/test_<name>.py`. Register fake tables with
   `fake.add_table(...)` and call the tools through the `make_client` fixture;
   cover the happy path, ordering, empty results, sample-data notes and bad
   arguments. `tests/test_server.py` already checks that every tool has a
   title, a description, read-only annotations, an output schema and described
   parameters.
6. **Live test.** Add `tests/live/test_live_<name>.py` with
   `pytestmark = [pytest.mark.live, pytest.mark.anyio, pytest.mark.skipif(...)]`
   like the existing files, and state its API call count in the module
   docstring. Assert what a free key really gets, and accept fixed end dates
   for tables Nasdaq no longer updates.
7. **Docs.** Run `uv run python scripts/generate_tool_docs.py`. It updates the
   README tables, writes `docs/tools/<name>.mdx` and adds the page to
   `docs/docs.json`. Then update the hand-written places that list toolsets:
   the `NDL_TOOLSETS` description in `server.json`, `.env.example`,
   `docs/configuration.mdx` and `docs/introduction.mdx`, and the server
   instructions in `nasdaq_data_link_mcp_os/instructions.py` if the routing
   advice changes.

## Reporting bugs and proposing features

Open an issue with the version (`nasdaq-data-link-mcp --version`), the client,
the tool call and its result or error (remove your API key), and what you
expected. For a feature or a new dataset, say which tables it would read and
what a free key gets from them. Report security problems privately as
described in [SECURITY.md](SECURITY.md).
