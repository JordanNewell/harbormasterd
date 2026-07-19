# 🚢 Port Authority

> **Zero-thinking port management with automatic HTTPS and DNS for local development**

Port Authority transforms local development by providing intelligent port management, automatic HTTPS certificates, and seamless DNS resolution. No more port conflicts, manual certificate setup, or remembering localhost URLs.

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

🔧 **Production-Ready**  
- Comprehensive testing suite (12 test categories)
- CI/CD pipeline with 9 platform combinations  
- Performance benchmarking and regression detection
- Enterprise-grade security and certificate management

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the daemon
python port_authority_daemon.py &

# 3. Validate your setup
pa selftest

# 4. Enable zero-config HTTPS and DNS (optional but recommended)
pa tls trust    # Setup certificates  
pa dns install  # Configure DNS resolver

# 5. Start developing with zero friction
pa run --name=myapp --prefer=3000 python app.py
# → Available at https://myapp.pa.local (automatic HTTPS!)
```

## 📋 Platform Commands

### Context Management
```bash
pa context list                    # List available contexts
pa context create team --daemon-url=https://team.example.com
pa context use team                # Switch to team context
```

### DNS & TLS Setup  
```bash
pa dns install                     # Install local DNS resolver
pa dns status                      # Check DNS status
pa tls trust                       # Setup HTTPS certificates
pa tls list                        # Show available certificates
```

### Service Management
```bash
pa run --name=api python server.py          # Start with auto port
pa open api                                  # Open in browser  
pa url api                                   # Get service URL
pa routes list                               # Show active routes
```

### Monitoring & Debugging
```bash
pa metrics                         # Show platform metrics
pa top                             # Live monitoring TUI
pa selftest                        # Quick health check
pa selftest --comprehensive        # Full integration test
```

## 🔧 Configuration

### Environment Variables

```bash
export PAD_URL="http://127.0.0.1:9999"              # Daemon URL
export PAD_ADMIN_TOKEN="REPLACED_BY_TOKEN_STORE"   # Admin API key
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

### Policy Configuration (`core/port-authority/data/policy.yaml`)

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
python core/port-authority/pad.py --log-level debug
```

### Permissions Issues (Windows)

```bash
# Run as administrator for ports 80/443
# Or configure Windows firewall rules
netsh http add urlacl url=http://+:80/ user=Everyone
```

### CLI Not Found

```bash
# Make sure Python path is correct
python core/port-authority/pa.py --help

# Create alias for convenience
alias pa="python $(pwd)/core/port-authority/pa.py"
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

- ✅ **Zero "port already in use" errors**
- ✅ **Sub-2-second startup times** with `pa run`
- ✅ **>95% automatic conflict resolution**
- ✅ **Beautiful *.pa.local URLs** instead of port numbers
- ✅ **Real-time port monitoring** and auto-healing

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
- **Platform Matrix**: Ubuntu, macOS, Windows × Python 3.9-3.11
- **Test Coverage**: 9 platform combinations  
- **Runtime**: < 10 minutes total
- **Validation**: DNS, TLS, routing, conflicts, performance

See [`TESTING.md`](TESTING.md) for complete testing documentation.

## 📊 Performance

### Benchmarks
- **Port Reservation**: < 50ms average
- **Conflict Detection**: < 25ms  
- **DNS Resolution**: < 5ms local queries
- **TLS Setup**: < 3s certificate installation
- **CI Pipeline**: < 10min (9 platforms in parallel)

### Success Criteria
✅ **8/8 self-tests pass** on all platforms  
✅ **< 100ms** average operation latency  
✅ **Zero-config setup** for DNS and TLS  
✅ **Graceful fallbacks** for optional features

## 🔧 Development

### Local Development
```bash
# Install development dependencies
pip install -r requirements.txt

# Run comprehensive tests
python -m pytest test_integration.py -v

# Start development daemon
python port_authority_daemon.py --admin-token=dev-token

# Test specific features
pa dns status
pa tls setup
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
- [GitHub Actions](`.github/workflows/test-platform.yml`) - CI pipeline configuration

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
- [ ] Docker integration for containerized development
- [ ] VS Code extension for seamless IDE integration
- [ ] Auto-discovery of development servers  
- [ ] Enhanced observability dashboard

### Medium Term  
- [ ] Team collaboration features
- [ ] Cloud deployment integration
- [ ] Advanced routing policies
- [ ] Plugin system for extensibility

### Long Term
- [ ] Kubernetes integration
- [ ] Multi-cluster management  
- [ ] Enterprise SSO integration
- [ ] Advanced security policies

## 🤝 Support

- **Issues**: [GitHub Issues](https://github.com/JordanNewell/port-authority/issues)
- **Discussions**: [GitHub Discussions](https://github.com/JordanNewell/port-authority/discussions)  
- **Documentation**: Complete guides and API reference
- **Community**: Discord server for real-time support

## 📋 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 🎉 Getting Started

Ready to eliminate port management friction from your development workflow?

```bash
# One command to rule them all
pa selftest --comprehensive && echo "🚢 Welcome aboard the Port Authority platform!"
```

**Port Authority**: Because developers should focus on building, not managing infrastructure.

---

*Developed with ❤️ by the Port Authority maintainers*  
*Platform tested on Windows 11, macOS Ventura, Ubuntu 22.04*  
*Comprehensive CI/CD pipeline validates every commit across 9 platform combinations*
