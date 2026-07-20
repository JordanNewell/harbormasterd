# Product Requirement Document (PRD): Harbormasterd

## 1. Executive Summary
Harbormasterd is a "zero-thinking" port management platform for local development. It automates HTTPS certificate generation, local DNS resolution (`*.pa.local`), and intelligent port conflict resolution, eliminating the friction of manual networking configuration for developers.

## 2. Problem Statement
Developers often waste time managing `localhost` port conflicts, manually setting up `mkcert` or self-signed certificates, and editing `/etc/hosts` or the Windows `hosts` file. These manual tasks are error-prone and disrupt the development flow, especially when working on multi-service micro-frontend or API architectures.

## 3. Target Audience
- Full-stack Developers
- Engineering Teams managing multiple local microservices
- DevOps Engineers standardizing local dev environments
- Next.js / Framework developers

## 4. Goals & Vision
- **Zero Friction**: Make local HTTPS and DNS "just work" with one command.
- **Auto-Healing**: Automatically detect and resolve port conflicts.
- **Cross-Platform**: Provide a unified experience across Windows, macOS, and Linux.
- **Visibility**: Provide a "top"-like view of all active local services and ports.

## 5. Core Features
### 5.1 Intelligent Port Management
- Smart port assignment based on preference and availability.
- Conflict detection and automatic reassignment (Auto-Heal).

### 5.2 Automatic TLS & DNS
- Local DNS resolver for `*.pa.local` domains (Hosts/mDNS/systemd-resolved integration).
- Automated TLS certificate management (mkcert/Caddy integration with system trust store).

### 5.3 Developer CLI
- `pa run`: Start services with auto-port and environment injection.
- `pa top`: Live monitoring TUI for services and metrics.
- `pa context`: Switch between configurations (local today; team-shared daemon mode is on the roadmap).

### 5.4 Framework Awareness
- Auto-detection of frameworks (Next.js, etc.) and injection of the correct `PORT` variable.

## 6. Technical Architecture
- **Language**: Python 3.9+
- **Daemon (`pad`)**: FastAPI service that owns the lease registry, gateway routes, and policy. DNS installation and TLS issuance are invoked by the CLI against the host OS, not by the daemon.
- **CLI**: `pa` (developer), `pa-platform` (platform setup), both token-authenticated clients of the daemon.
- **Gateway**: pluggable driver (`TraefikDriver` file provider, `CaddyDriver` admin API).
- **DNS Core**: Platform-specific handlers for Windows (hosts file), macOS (resolver files), and Linux (systemd-resolved / dnsmasq).

## 7. Performance Targets
- **Reservation Latency**: <50ms
- **Startup Time**: <2 seconds for `pa run`.
- **Conflict Resolution**: automatic reassignment to the ephemeral range when a preferred port is busy.

## 8. Success Metrics
- **Developer Productivity**: Measure time saved on networking setup per dev.
- **Platform Reliability**: passing the in-process endpoint test suite (`test_pad_endpoints.py`) across the CI matrix.
- **User Engagement**: Adoption of `pa run` as the primary entry point for local development.

## 9. Status (2026-07-20)
Sections 5.1–5.4 are implemented and covered by the test suite. Not yet built:
team-shared daemon mode / tunneling (`pa share`), audit-log read endpoint,
VS Code extension, Docker/Kubernetes integration. These live in the README roadmap.
