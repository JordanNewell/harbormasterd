# Contributing

Thanks for considering a contribution to **harbormasterd** — zero-conflict
port management with automatic HTTPS and DNS for local development. This
doc covers dev setup, testing, code style, and PR expectations.

External PRs for bug fixes and platform coverage are welcome. For larger
feature work, please open an issue first to scope the change.

## Dev setup

Requires **Python ≥ 3.10**.

```bash
git clone https://github.com/JordanNewell/harbormasterd.git
cd harbormasterd
pip install -e ".[dev]"      # installs pytest, pytest-cov, pytest-asyncio,
                             # httpx, black, mypy
```

The `dev` extra (defined in `pyproject.toml` under
`[project.optional-dependencies]`) is the canonical dependency list — don't
add runtime deps to your branch without raising it in an issue first.

### Run the platform locally

```bash
pa --help                   # CLI entrypoint (port-assign)
pad --help                  # daemon entrypoint
pa-platform --help          # platform/orchestration entrypoint
```

`INSTALL.md` has the full setup walkthrough including daemon startup.

## Testing

Tests live at the repo root (flat layout matching the source modules —
not in a `tests/` subdirectory):

- `test_token_store.py` — credential storage round-trip
- `test_pad_endpoints.py` — FastAPI endpoint coverage
- `test_integration.py` — full TestHarness (cross-platform routing, TLS,
  conflict auto-heal, WebSocket proxy, perf benchmarks)
- `test_connection.py` — daemon connectivity

### Run the suite

```bash
python -m pytest test_token_store.py test_pad_endpoints.py -v
python -m pytest                                       # entire suite
python -m pytest --cov=pa --cov=pad --cov-report=term # with coverage
```

CI runs `test_token_store.py` + `test_pad_endpoints.py` only (see
`.github/workflows/ci.yml`) — these are the gates. The integration suite
requires a running daemon and an admin token, so it's manual / opt-in via
`pa-platform selftest --comprehensive`.

### Built-in self-test

The platform ships its own self-test command:

```bash
pa-platform selftest                  # 8 core checks, no daemon admin token needed
pa-platform selftest --comprehensive  # runs the full TestHarness
pa-platform selftest --json           # JSON output for CI / automation
```

When fixing a bug, add a regression under `test_token_store.py` or
`test_pad_endpoints.py` that fails before your fix and passes after.

## Code style

- **`black` formatting, line length 100.** Configured under
  `[tool.black]` in `pyproject.toml`. Run `black .` before sending a PR.
- **`mypy` strict-ish typing.** Config: `warn_return_any = true`,
  `warn_unused_configs = true`. New code should be typed; untyped legacy
  modules are being migrated incrementally.
- **`pyproject.toml` is the source of truth** for tool config. No
  `setup.cfg`, no `tox.ini`, no `.flake8`.
- **No `Any`** without a comment explaining why. Prefer `unknown` plus a
  runtime guard at the boundary.
- **Comments explain *why*, not *what*** — if a comment just restates the
  code below it, delete it.
- **Python 3.10 baseline.** Don't use 3.11+ syntax (`Self`, `ExceptionGroup`,
  `tomllib`) without gating — the classifiers explicitly support 3.10.

## Commits

- Subject ≤ 72 chars, imperative mood (`Add X`, `Fix Y`).
- Conventional-commit prefixes (`feat:`, `fix:`, `docs:`, `chore:`,
  `refactor:`) are used in this repo — match them when you can.
- Reference the issue number in the body if applicable.
- **No `Co-Authored-By: Claude` or any AI-attribution trailer.** Tools
  don't get attribution; humans do.

## Pull requests

Open a PR against `master`. CI must pass — the matrix is **Ubuntu /
macOS / Windows × Python 3.10 / 3.11 / 3.12 / 3.13** (12 combinations,
see `.github/workflows/ci.yml`). Fail-fast is off, so you'll see every
platform's result.

Before requesting review:

- [ ] `black .` produces no diff
- [ ] `mypy .` is clean (or warnings are pre-existing and noted)
- [ ] `python -m pytest test_token_store.py test_pad_endpoints.py -v` passes
- [ ] `pa-platform selftest` passes locally (the 8-check quick mode)
- [ ] `python -m build` produces a working wheel
- [ ] No new runtime dependencies in `pyproject.toml` without an issue
- [ ] `README.md` / `INSTALL.md` updated if user-visible behavior changed

### Release flow

Releases are automated via GitHub Actions on `v*` tag push. The publish
job uses the `PYPI_API_TOKEN` repository secret (exact name). **Don't
push tags as part of a PR** — a maintainer cuts the release.

To bump the version, edit `pyproject.toml`'s `version = "..."` line and
if/when a CHANGELOG.md is introduced, note the change there. The CI build picks it up automatically.

## Filing issues

- 🐛 **Bugs** — include the OS, Python version, output of `pa --version`
  (or the daemon log), and a minimal reproduction. If a port conflict or
  TLS failure is involved, paste the relevant `pa` subcommand's stderr.
- ✨ **Features** — describe the workflow you want, not the implementation.
  Concrete examples beat abstract proposals.
- 📚 **Docs** — typos, dead links, missing detail. PRs to docs will be
  considered even during the no-PR window for code.

## Security disclosures

harbormasterd handles TLS private keys and admin tokens. Do **not** open
a public issue for vulnerabilities in token storage, TLS material
handling, or the admin-token auth path. See [`SECURITY.md`](SECURITY.md)
for the private reporting path.

## License

By contributing, you agree your contributions are licensed under the
[MIT license](LICENSE).