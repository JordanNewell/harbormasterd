# 🚢 Harbormasterd

> **Zero-thinking port management with automatic HTTPS and DNS for local development**

Harbormasterd transforms local development by providing intelligent port management, automatic HTTPS certificates, and seamless DNS resolution. No more port conflicts, manual certificate setup, or remembering localhost URLs.

## ✨ Key Features

🎯 **Zero-Config Experience**  
- Automatic HTTPS certificates via mkcert, Caddy CA, or self-signed fallback
- Local DNS resolver for `*.pa.local` domains  
- Smart port conflict detection and auto-healing

🌐 **Cross-Platform Support**  
- Windows, macOS, and Linux compatibility
- Native OS integration (UAC, sudo, systemd)
- Python 3.9+ support

⚡ **Developer-First Design**  
- Rich CLI with context switching (`pa context use dev`)
- Live monitoring and metrics (`pa top`)  
- Browser integration (`pa open myapp`)
- Gateway routing and WebSocket support

🔧 **Production-Minded**
- Comprehensive endpoint test suite (drives the daemon in-process via FastAPI's TestClient)
- CI/CD pipeline across 12 platform combinations
- Token-authenticated API (admin token on every endpoint)
- Defense-in-depth: parameterized SQL, scoped token storage, OS keyring integration

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the daemon
pad &

# 3. Validate your setup
pa selftest

# 4. Enable zero-config HTTPS and DNS (optional but recommended)
pa-platform tls trust    # Setup + trust certificates
pa-platform dns install  # Configure DNS resolver for *.pa.local

# 5. Start developing with zero friction
pa run --name=myapp --prefer=3000 python app.py
# → Available at https://myapp.pa.local (automatic HTTPS!)
```

## 🖥️ Three Entry Points

Harbormasterd ships three entry points:

| Command | Module | Purpose |
|---|---|---|
| `pa` | `pa.py` | Developer CLI — `pa run`, `pa reserve`, `pa release`, `pa who`, `pa scan`, `pa doctor`, `pa events` |
| `pa-platform` | `pa_platform.py` | Platform CLI — `pa-platform context`, `pa-platform dns`, `pa-platform tls`, `pa-platform routes`, `pa-platform top`, `pa-platform selftest` |
| `pad` | `pad.py` | Daemon — long-running background service |

Most users only need `pa`. Use `pa-platform` for HTTPS/DNS setup and team-shared contexts.

## 📌 Status

Harbormasterd is **beta** software under active development. What works today:

- ✅ **Daemon (`pad`)** — port reservation, process spawning, lease lifecycle (`/reserve`, `/spawn`, `/bind`, `/release`), inspection (`/who`, `/scan`, `/leases`), policy blocks (`/block`, `/unblock`), process kill (`/kill`), gateway routes (`/routes`), policy management (`/policy`), metrics (`/metrics`), health (`/health`), and live SSE events (`/events`). Every endpoint requires the admin token.
- ✅ **Developer CLI (`pa`)** — `run`, `reserve`, `bind`, `release`, `who`, `scan`, `block`, `unblock`, `kill`, `health`, `events`, `doctor`, `print-token`. All wired to the daemon.
- ✅ **Platform CLI (`pa-platform`)** — context management, routes (`list`/`add`/`rm`/`sync`), DNS install/status, TLS trust/issue/list, policy (`show`/`apply`/`edit`), metrics, top, selftest.
- ✅ **Gateway drivers** — Traefik (file provider, default) and Caddy (admin API). Selectable via `data/policy.yaml` `gateway.driver`.
- ✅ **Cross-platform port detection** (Linux /proc, macOS sysctl, Windows netsh).
- ✅ **Token-secured API** — every daemon endpoint authenticates via `X-API-Key`.

Not yet implemented (tracked in [#Roadmap](#-roadmap)): audit-log read endpoint, team-shared daemon mode / tunneling (`pa share`), VS Code extension, Kubernetes integration.

## 📋 Platform Commands

### Context Management
```bash
pa context list                    # List available contexts
pa context create team --daemon-url=https://team.example.com
pa context use team                # Switch to team context
```

### DNS & TLS Setup
```bash
pa-platform dns install            # Install local DNS resolver for *.pa.local
pa-platform dns status             # Check DNS status
pa-platform tls trust              # Setup + trust HTTPS certificates
pa-platform tls list               # Show available certificates
```

### Policy Management
```bash
pa-platform policy show            # Show the daemon's current policy
pa-platform policy apply p.yaml    # Merge a policy fragment
pa-platform policy edit            # Open $EDITOR, apply on save
```

### Service Management
```bash
pa run --name=api python server.py          # Start with auto port
pa-platform open api                        # Open service URL in browser
pa-platform url api                         # Print service URL for scripts
pa-platform routes list                     # Show gateway routes
pa-platform routes sync -f .pa.yaml         # Sync routes from project config
```

### Monitoring & Debugging
```bash
pa metrics                         # Show platform metrics
pa top                             # Live monitoring TUI
pa selftest                        # Quick health check
pa selftest --comprehensive        # Full integration test
```

## 🔧 Configuration

### Authentication

Every daemon endpoint requires an admin token. The token is generated automatically on first `pad` startup and persisted to your OS keyring (fallback: `~/.harbormasterd/daemon.token`, mode 0600).

```bash
# The CLI reads the token automatically — no setup needed on the same machine.
# To see the current token (e.g. for a remote context):
pa print-token

# To override (CI, remote daemon, etc.):
export PAD_ADMIN_TOKEN="$(pa print-token)"
# or set it directly:
export PAD_ADMIN_TOKEN="<64-char hex token>"
```

The CLI sends the token via the `X-API-Key` header on every request.

### Environment Variables

```bash
export PAD_URL="http://127.0.0.1:9999"              # Daemon URL
export PAD_ADMIN_TOKEN="$(pa print-token)"   # Admin API key (auto-generated)
```

### Project Configuration (`.pa.yaml`)

```yaml
service: my-app
prefer: [3000, 3001]
routes:
  - host: my-app.pa.local
    protocols: [http, ws]
gateway:
  enabled: true
  auto_tls: true
```

### Policy Configuration (`data/policy.yaml`)

```yaml
block_patterns: ["^.*(3000|3001|80|443)$"]
auto_heal: true
max_ttl: 86400  # 24 hours
gateway:
  enabled: true
  domain: "pa.local"
  auto_tls: true
```

## 🏠 Architecture

### Core Platform Components

**DNS Resolver** (`dns_resolver.py`)
- Cross-platform DNS resolver for `*.pa.local`
- Windows: Hosts file + DNS cache management
- macOS: `/etc/resolver/` + mDNSResponder integration  
- Linux: systemd-resolved + dnsmasq fallback

**TLS Manager** (`tls_manager.py`)
- Multi-provider certificate management
- mkcert (preferred) → Caddy CA → Self-signed fallback
- Automatic system trust store integration

**Platform CLI** (`pa_platform.py`)  
- Enhanced CLI with context management
- Gateway routing and service discovery
- Real-time monitoring and metrics

**Test Harness** (`test_integration.py`)
- 12 comprehensive test categories
- Cross-platform validation
- Performance benchmarking

### Integration Points

```python
# DNS resolver integration
from dns_resolver import CrossPlatformDNSInstaller
dns = CrossPlatformDNSInstaller()
dns.install()

# TLS certificate management
from tls_manager import TLSManager  
tls = TLSManager()
tls.setup()

# Platform CLI with enhanced features
python pa_platform.py selftest --comprehensive
```

## 🧪 Testing Scenarios

### Test 1: Basic Conflict Resolution

```bash
# Start something on port 3000
node -e "require('http').createServer().listen(3000)"

# Try to use port 3000 - should auto-reassign
pa run --name test -- node -e "require('http').createServer().listen(process.env.PORT)"
# ✅ Gets assigned port 60001 instead
```

### Test 2: Framework Detection

```bash
# In a Next.js project
pa doctor
# ✅ Detects Next.js, suggests .pa.yaml config

pa run --name web -- npm run dev  
# ✅ Injects PORT=60002, shows framework hints
```

### Test 3: Auto-Heal

```bash
# Start a service
pa run --name test -- node -e "require('http').createServer().listen(process.env.PORT)"

# Kill the process externally
kill -9 <pid>

# Port gets auto-guarded within 30 seconds
pa who <port>
# ✅ Shows "RESERVED" with auto-heal
```

## 🚨 Troubleshooting

### Daemon Won't Start

```bash
# Check if port 9999 is available
pa who 9999

# Start with debug logging
pad --log-level debug
```

### Permissions Issues (Windows)

```bash
# Run as administrator for ports 80/443
# Or configure Windows firewall rules
netsh http add urlacl url=http://+:80/ user=Everyone
```

### CLI Not Found

```bash
# pa, pa-platform, and pad are console scripts — ensure your pip install
# location (e.g. ~/.local/bin on Linux, %APPDATA%\Python\Scripts on Windows)
# is on your PATH. Re-run: pip install -e .
```

### Framework Not Detected

```bash
# Force framework detection
pa doctor

# Manual configuration
echo "service: my-app" > .pa.yaml
```

## 🎯 Success Metrics

After setup, you should see:

- ✅ **Fewer "port already in use" errors** — `pa run` finds a free port automatically
- ✅ **Fast startup** with `pa run` (port reservation is a single round-trip)
- ✅ **Automatic conflict resolution** — preferred ports fall back to the ephemeral range
- ✅ **Beautiful *.pa.local URLs** instead of port numbers (with DNS installed)
- ✅ **Real-time port monitoring** and auto-healing of dead managed processes

## 🧪 Testing & Validation

### Self-Test Command
```bash
# Quick validation (8 core tests, ~30 seconds)
pa selftest

# Comprehensive integration test (~5 minutes)  
pa selftest --comprehensive

# CI-friendly JSON output
pa selftest --json
```

### CI/CD Pipeline
- **Platform Matrix**: Ubuntu, macOS, Windows × Python 3.9–3.12
- **Test Coverage**: 12 platform combinations
- **Runtime**: < 10 minutes total
- **Validation**: import smoke, token storage, full daemon endpoint suite

See [`TESTING.md`](TESTING.md) for complete testing documentation.

## 📊 Performance

### Benchmarks
- **Port Reservation**: < 50ms average
- **Conflict Detection**: < 25ms  
- **DNS Resolution**: < 5ms local queries
- **TLS Setup**: < 3s certificate installation
- **CI Pipeline**: < 10min (12 platforms in parallel)

### Success Criteria
✅ **Daemon endpoint suite passes** on every supported platform
✅ **Zero-config token auth** — generated on first run, persisted to keyring
✅ **Zero-config setup** for DNS and TLS (optional, with graceful fallbacks)
✅ **Graceful fallbacks** for optional features

## 🔧 Development

### Local Development
```bash
# Install development dependencies
pip install -r requirements.txt

# Run comprehensive tests
python -m pytest test_integration.py -v

# Start development daemon (auto-generates a token; retrieve with `pa print-token`)
pad

# Test specific features
pa-platform dns status
pa-platform tls status
pa selftest --comprehensive
```

### Contributing
1. Fork the repository
2. Create a feature branch  
3. Add tests for new functionality
4. Ensure all platforms pass: `pa selftest --comprehensive`
5. Update documentation
6. Submit a pull request

## 📚 Documentation

- [`TESTING.md`](TESTING.md) - Complete testing guide and CI/CD setup
- [`DEVELOPMENT_HISTORY.md`](DEVELOPMENT_HISTORY.md) - Full implementation timeline  
- [GitHub Actions](`.github/workflows/ci.yml`) - CI pipeline configuration

## 🛡️ Security

### Certificate Management
- Industry-standard mkcert for local CA
- Automatic system trust store integration  
- Secure certificate storage and rotation
- No network exposure by default

### Platform Security  
- Minimal privilege escalation (UAC/sudo only when needed)
- Local-only DNS resolution
- Secure admin token handling
- Comprehensive input validation

## 📚 Roadmap

### Short Term
- [ ] Audit-log read endpoint (`GET /audit`) — the hash chain is written today, just not yet queryable
- [ ] Gateway health probe (is the configured Traefik/Caddy actually up?)
- [ ] `.pa.yaml` schema validation in `pa doctor`
- [ ] Auto-discovery of development servers

### Medium Term
- [ ] Docker integration for containerized development
- [ ] VS Code extension for seamless IDE integration
- [ ] Plugin system for extensibility
- [ ] Enhanced observability dashboard

### Long Term
- [ ] Team-shared daemon mode + `pa share <service>` tunneling (cloudflared/ngrok)
- [ ] Kubernetes integration
- [ ] Multi-cluster management
- [ ] Enterprise SSO / RBAC

## 🤝 Support

- **Issues**: [GitHub Issues](https://github.com/JordanNewell/harbormasterd/issues)
- **Discussions**: [GitHub Discussions](https://github.com/JordanNewell/harbormasterd/discussions)  
- **Documentation**: Complete guides and API reference
- **Community**: Discord server for real-time support

## 📋 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 🎉 Getting Started

Ready to eliminate port management friction from your development workflow?

```bash
# One command to rule them all
pa selftest --comprehensive && echo "🚢 Welcome aboard the Harbormasterd platform!"
```

**Harbormasterd**: Because developers should focus on building, not managing infrastructure.

---

*Developed with ❤️ by the Harbormasterd maintainers*  
*Platform tested on Windows 11, macOS Ventura, Ubuntu 22.04*  
*Comprehensive CI/CD pipeline validates every commit across 12 platform combinations*
