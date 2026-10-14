# Changelog

All notable changes to Harbormasterd are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] — 2026-07-20

### Added

- **New daemon endpoints:** `/routes`, `/policy`, `/scan`, `/metrics`
  (with legacy response shapes for backward compatibility).
- **In-process endpoint test suite:** 39 tests running in CI.
- **CI matrix:** dropped EOL Python 3.9, added 3.13.

### Fixed

- **Null-PID `/kill` footgun:** daemon now refuses `/kill` on a
  RESERVED lease without a bound PID.
- **`pa-platform` run-twice regression:** 409 from a duplicate route
  is now swallowed instead of erroring out.

### Changed

- Semver minor bump per the new endpoint surface.

## [1.0.1] — 2026-07-19

Initial PyPI release as `harbormasterd` (renamed from `port-authority`
due to a PyPI name collision with the existing `portauthority`
package, versions 0.2.0-0.2.2 dropped May 2026 with a suspiciously
similar tagline).

### Added

- **Zero-conflict port management platform.** Automated port conflict
  resolution, local DNS (`*.pa.local`), TLS certificate management
  (mkcert/Caddy CA/self-signed), and gateway routing for local
  development.
- **Three console scripts:** `pa` (developer CLI: run, reserve,
  release, scan, doctor), `pa-platform` (platform CLI: context, dns,
  tls, routes, top, selftest), `pad` (daemon — FastAPI on
  `127.0.0.1:9999`).
- **Secure per-install admin token** via keyring primary,
  `~/.harbormasterd/daemon.token` file fallback. Auto-generated at
  daemon start; retrieved via `pa print-token`.
- **CI:** master trigger + tag-gated publish + import smoke test.

### Changed

- **Brand rename Port Authority -> Harbormasterd.** PyPI rejected
  `port-authority` upload with HTTP 400 (normalizes to `portauthority`,
  owned by another publisher). Renamed PyPI package, all source/doc
  files, config paths (`~/.port-authority/` -> `~/.harbormasterd/`),
  and `KEYRING_SERVICE`. Repo renamed
  `JordanNewell/port-authority` -> `JordanNewell/harbormasterd`
  (old URLs auto-redirect).
- **De-branded internal codenames:** 60+ references across 18 files.
- **Flat py-modules layout** in `pyproject.toml`; all deps declared.
- **`pyproject.toml` email hygiene:** `noreply` GitHub email.
- **Daemon version strings** synced to 1.0.1.

### Fixed

- **Windows Unicode crash** in `pa` / `pa_platform` CLIs.
- **pyproject packaging** (flat py-modules layout, all deps declared).

### Preserved

- Console scripts `pa` / `pa-platform` / `pad` (functional names, not
  brand).
- DNS gateway domain `pa.local` (internal hostname, not user-facing).
- `v1.0.0` hardcoded token name `curtis-port-authority-pro` as a
  historical fact in `DEVELOPMENT_HISTORY.md`.

[Unreleased]: https://github.com/JordanNewell/harbormasterd/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/JordanNewell/harbormasterd/releases/tag/v1.1.0
[1.0.1]: https://github.com/JordanNewell/harbormasterd/releases/tag/v1.0.1