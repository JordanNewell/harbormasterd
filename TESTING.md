# 🧪 Harbormasterd Testing Guide

This document describes the testing strategy and CI/CD pipeline for the Harbormasterd platform.

## Overview

The Harbormasterd platform includes comprehensive testing across multiple dimensions:

- **Cross-platform compatibility** (Ubuntu, macOS, Windows)  
- **Python version support** (3.9, 3.10, 3.11)
- **DNS resolution validation**
- **TLS certificate management** 
- **Port conflict detection and auto-healing**
- **Gateway routing and WebSocket support**
- **Performance benchmarking**

## Testing Architecture

### 1. Self-Test Command (`pa selftest`)

The platform includes a built-in self-test command with two modes:

```bash
# Quick self-test (8 core tests)
pa selftest

# Comprehensive integration test suite
pa selftest --comprehensive

# JSON output for CI/automation
pa selftest --json
```

#### Quick Self-Test (Standard Mode)
- ✅ Daemon connectivity
- ✅ Port reservation/release cycle
- ✅ DNS resolution validation
- ✅ TLS certificate availability
- ✅ Gateway integration
- ✅ Metrics collection  
- ✅ Process spawning (if admin token available)
- ✅ Performance check (< 100ms avg)

#### Comprehensive Mode
Runs the full integration test harness (`test_integration.py`) covering:
- Cross-platform routing tests
- TLS certificate validation
- Conflict detection and auto-healing
- Port blocking and policy enforcement  
- WebSocket proxying
- Performance benchmarks
- End-to-end developer workflow

### 2. Integration Test Harness

The `test_integration.py` provides a complete test suite that can be run standalone or via the platform CLI:

```python
from test_integration import TestHarness

harness = TestHarness({
    'daemon_url': 'http://127.0.0.1:9999',
    'admin_token': 'your-admin-token',
    'domain': 'pa.local'
})

results = harness.run_all_tests()
```

## CI/CD Pipeline

### GitHub Actions Workflow

The `.github/workflows/test-platform.yml` runs comprehensive tests on every push/PR:

#### Test Matrix
- **Platforms**: Ubuntu, macOS, Windows
- **Python**: 3.9, 3.10, 3.11  
- **Total**: 9 platform combinations
- **Timeout**: 10 minutes per combination

#### Test Stages

1. **System Setup**
   - Install platform dependencies
   - Pre-install mkcert for TLS testing
   - Setup Python environment

2. **Platform Self-Test**
   ```bash
   python pa_platform.py selftest --json
   ```

3. **Comprehensive Testing** (Ubuntu + Python 3.11 only)
   ```bash
   python pa_platform.py selftest --comprehensive --json
   ```

4. **DNS Resolver Testing** (Linux/macOS)
   - Install → Status Check → Uninstall
   - Validates cross-platform DNS integration

5. **TLS Certificate Testing**
   - mkcert setup validation
   - Caddy CA fallback testing
   - Self-signed certificate generation

6. **Performance Benchmarking**
   - 10-iteration port reservation benchmark
   - Performance threshold validation (< 500ms)

### Test Results & Artifacts

Each test run produces:
- `selftest-results.json` - Quick test results
- `comprehensive-results.json` - Full integration results  
- `system-info.json` - Platform details
- `harbormasterd.log` - Daemon logs (if available)

### Success Criteria

#### Individual Platform Tests
- ✅ All 8 self-tests pass
- ✅ Performance < 500ms average
- ✅ DNS/TLS setup successful or gracefully fallback

#### Overall Pipeline
- ✅ All platform combinations pass
- ✅ Comprehensive tests pass (Ubuntu)
- ✅ Performance benchmarks within threshold
- ✅ No critical regressions detected

### Performance Tracking

Performance metrics are tracked on the `main` branch:
- Port reservation latency
- Conflict detection speed
- Auto-healing response time  
- Memory usage patterns

Results stored as artifacts for historical analysis.

## Local Testing

### Quick Local Test
```bash
# Start daemon
python harbormasterd_daemon.py &

# Run self-test
python pa_platform.py selftest

# Or comprehensive
python pa_platform.py selftest --comprehensive
```

### Development Workflow
```bash
# Install dependencies
pip install -r requirements.txt

# Run specific test categories
python -m pytest test_integration.py::TestHarness::test_port_conflicts
python -m pytest test_integration.py::TestHarness::test_dns_resolution  
python -m pytest test_integration.py::TestHarness::test_tls_certificates
```

### Manual DNS/TLS Testing
```bash
# Test DNS resolver
pa dns install
pa dns status  
pa dns uninstall

# Test TLS certificates
pa tls trust
pa tls status
pa tls list
```

## Error Handling & Debugging

### Common Issues

1. **Daemon Connection Failed**
   ```
   ❌ Could not connect to Harbormasterd daemon
   ```
   **Solution**: Start daemon with `python harbormasterd_daemon.py`

2. **DNS Resolution Failing**
   ```
   ⚠️  DNS server running but resolution failing
   ```
   **Solution**: Check system DNS configuration, may need admin rights

3. **TLS Setup Failed**
   ```
   ❌ TLS setup failed
   ```
   **Solution**: Install mkcert manually or check system certificate store

4. **Performance Slow**
   ```
   ⚠️  Performance slow (250ms avg)
   ```
   **Solution**: Check system load, daemon resources

### Debug Mode

Enable verbose logging:
```bash
export PAD_LOG_LEVEL=DEBUG
python pa_platform.py selftest --comprehensive
```

### CI Debug

Download test artifacts from failed runs:
- Navigate to Actions → Failed workflow
- Download `test-results-{os}-python{version}` artifacts
- Review JSON results and system info

## Contributing

### Adding New Tests

1. **Add to Self-Test**: Edit `pa_platform.py` selftest command
2. **Add to Integration**: Edit `test_integration.py` TestHarness class  
3. **Update CI**: Modify `.github/workflows/test-platform.yml` if needed

### Test Guidelines

- Tests should complete in < 10 minutes total
- Use descriptive error messages with emojis
- Graceful handling of optional features (DNS/TLS)
- Performance tests should have reasonable thresholds
- Clean up resources (ports, processes, files)

### Performance Standards

- Port reservation: < 100ms average
- Conflict detection: < 50ms
- Auto-healing: < 200ms
- DNS resolution: < 50ms
- TLS certificate generation: < 2s

---

## Test Coverage Matrix

| Feature | Quick Test | Comprehensive | Platform Coverage |
|---------|------------|---------------|-------------------|
| Daemon Health | ✅ | ✅ | All |
| Port Management | ✅ | ✅ | All |  
| DNS Resolution | ⚠️ | ✅ | Linux/macOS |
| TLS Certificates | ⚠️ | ✅ | All |
| Gateway Routing | ⚠️ | ✅ | All |
| Conflict Detection | ❌ | ✅ | All |
| Auto-Healing | ❌ | ✅ | All |
| WebSocket Proxy | ❌ | ✅ | All |
| Performance | ✅ | ✅ | All |

**Legend:**
- ✅ Full testing
- ⚠️ Basic validation  
- ❌ Not covered

The comprehensive testing ensures Harbormasterd works reliably across all supported platforms and provides a smooth zero-config developer experience.

---

🚢 **Ready to test?** Start with `pa selftest` and build confidence in your Harbormasterd setup!
