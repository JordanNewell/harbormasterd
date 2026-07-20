# 🚢 Harbormasterd — Platform Summary

A local-development port-management platform: intelligent port allocation,
automatic conflict resolution, `*.pa.local` gateway URLs, and local DNS/TLS.

This document describes what the platform **actually does today**. Aspirational
items live in the README roadmap.

## 🎯 Problem Solved

**Original issue:** "Everything gets put on port 3000" — constant port
conflicts destroying developer productivity.

**Solution:** A daemon-backed registry that reserves ports atomically,
guards them against races, auto-heals dead processes, and (optionally)
projects friendly `*.pa.local` URLs through a gateway driver.

## 🏗️ Architecture

### Core components

| Component | File | Purpose |
|-----------|------|---------|
| **Daemon** | `pad.py` | FastAPI service with SQLite registry, socket guards, SSE events, gateway drivers |
| **Developer CLI** | `pa.py` | `pa run`, `reserve`, `release`, `bind`, `who`, `scan`, `block`, `unblock`, `kill`, `events`, `doctor`, `print-token` |
| **Platform CLI** | `pa_platform.py` | Contexts, routes, DNS/TLS, policy, metrics, selftest |
| **Gateway drivers** | `pad.py` (Traefik), `drivers/caddy.py` (Caddy) | Pluggable reverse-proxy integration |
| **DNS resolver** | `dns_resolver.py` | Cross-platform `*.pa.local` installer |
| **TLS manager** | `tls_manager.py` | mkcert / Caddy CA / self-signed certificate management |
| **Token store** | `token_store.py` | Admin-token persistence (keyring → mode-0600 file → env) |

### Platform pillars

#### 1. 🌍 Contexts & namespaces
```bash
pa-platform context create team --daemon-url https://ports.team.example.com
pa-platform context use team
pa-platform run --name web -- npm start   # runs in team/web namespace
```
- Per-context daemon URL, namespace, and token
- Namespaced route names so multiple contexts can coexist

#### 2. 🌐 Routes & gateway control
```bash
pa-platform routes add web.pa.local http://127.0.0.1:3000 --protocols http,ws
pa-platform routes list
pa-platform routes rm web.pa.local
pa-platform routes sync -f .pa.yaml   # POST routes declared in a project file
pa-platform open web                   # opens the service URL in a browser
pa-platform url  web                   # prints the URL for scripts
```
- Backed by `GET/POST/DELETE /routes` on the daemon
- Gateway-driver selectable via policy (`gateway.driver: traefik|caddy`)
- Routes persist across daemon restarts (`data/routes.json`)

#### 3. 🔒 DNS & TLS management
```bash
pa-platform dns install     # local DNS resolver for *.pa.local
pa-platform dns status
pa-platform tls trust       # trust the local CA
pa-platform tls issue web.pa.local
pa-platform tls list
```
- Cross-platform DNS install (hosts file / systemd-resolved / resolver files)
- TLS provider fallback chain: mkcert → Caddy CA → self-signed

#### 4. 📋 Policy & audit
```bash
pa-platform policy show                 # current policy
pa-platform policy apply policy.yaml    # merge a fragment
pa-platform policy edit                 # $EDITOR on the policy, applied on save
```
Policy fields actually consulted by the daemon:

| Field | Effect |
|---|---|
| `block_patterns` | Ports matching these regexes are auto-blocked on startup |
| `auto_heal` | Re-guard ports whose bound PID has died |
| `max_ttl` | Clamp lease TTL in `/reserve` and `/spawn` |
| `require_admin_for_kill` | If false, `/kill` does not require the admin token |
| `audit_enabled` | Toggle the tamper-evident audit log |
| `gateway.driver` | Select `traefik` or `caddy` |

#### 5. 📊 Observability
```bash
pa metrics            # gauges + counters
pa top                # live TUI of managed + unmanaged ports
pa selftest           # 8 quick checks (daemon, reserve/release, DNS, TLS, gateway, metrics, spawn, perf)
pa selftest --comprehensive   # 13-category integration suite
```
- `/metrics` returns nested `counters`/`gauges` plus flat aliases for legacy clients
- `/scan` returns both canonical (`managed`/`unmanaged`) and legacy (`active_ports`/`conflicts`) shapes

## ✨ Features

### Atomic, race-free allocation
- **Atomic spawn**: reserve → guard → launch in one operation
- **Socket guards**: the daemon physically holds ports to prevent races
- **Auto-heal**: dead managed processes get their ports re-guarded

### Intelligent assignment
- Framework detection (Next.js, Vite, Django, FastAPI, Express, Vue CLI, CRA)
- Smart reassignment: preferred ports fall back to the ephemeral range
- Policy-driven blocking and TTL clamping

### Security model
- **Every endpoint requires the admin token** (X-API-Key header) by default
- Token persisted to the OS keyring with a mode-0600 file fallback
- `/kill` can be opened to unauthenticated callers via policy (off by default)
- SQL is parameterized throughout; no string interpolation in queries
- Tamper-evident audit log (SHA-256 chain)

## 🚀 Installation & usage

### Quick setup
```bash
pip install -e ".[dev]"   # or: pip install -r requirements.txt
pad                       # start the daemon (auto-generates a token)
pa print-token            # see the token (set PAD_ADMIN_TOKEN to use it)
pa selftest               # validate
```

### Commands at a glance
```bash
# Developer CLI (pa)
pa run --name web -- npm start
pa reserve --name api --prefer 3000 3001
pa release --name api
pa who 3000
pa scan
pa block 5432 --reason "postgres reserved"
pa kill 3000 --force
pa events
pa doctor

# Platform CLI (pa-platform)
pa-platform context list|use|create|delete
pa-platform routes list|add|rm|sync
pa-platform open <service>
pa-platform url <service>
pa-platform dns install|status|uninstall
pa-platform tls trust|issue|list|status
pa-platform policy show|apply|edit
pa-platform metrics
pa-platform top
pa-platform selftest [--comprehensive]
```

## 📊 Status

| Capability | Status |
|---|---|
| Port reservation, binding, release | ✅ shipped |
| Process spawn + auto-heal | ✅ shipped |
| Policy blocks + TTL clamping | ✅ shipped |
| Gateway routes (Traefik + Caddy drivers) | ✅ shipped |
| Policy hot-reload via `/policy` | ✅ shipped |
| Local DNS resolver | ✅ shipped |
| TLS management (mkcert/Caddy/self-signed) | ✅ shipped |
| Token-authenticated API on every endpoint | ✅ shipped |
| Audit log (hash chain) | ✅ shipped (written; no read endpoint yet) |
| Team-shared daemon / tunneling | 🚧 not yet (roadmap) |
| VS Code extension, Docker/K8s, RBAC, service mesh | 🚧 not yet (roadmap) |

## 🔮 Roadmap

Short term:
- Audit-log read endpoint (`GET /audit`)
- Gateway health probes (is the configured Traefik/Caddy actually up?)
- `.pa.yaml` schema validation in `pa doctor`

Longer term:
- VS Code extension
- Docker Compose / Kubernetes integration
- Team tunnels (`pa share`) for secure sharing beyond the local machine
- Multi-host coordination, RBAC, service-mesh integration

See the README for the full roadmap and current disclaimers.

---

**🚢 Harbormasterd** — *Making port conflicts a thing of the past, on this machine.*
