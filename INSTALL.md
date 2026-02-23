# 🚢 Install Port Authority

## One-Line Install (Coming Soon)

```bash
curl -sSf https://install.portauthority.dev | sh
```

## Install from PyPI (Coming Soon)

```bash
pip install port-authority
```

## Manual Install

```bash
# Clone the repo
git clone https://github.com/curtis-ai/port-authority.git
cd port-authority

# Install dependencies
pip install -r requirements.txt

# Run self-test to verify installation
python pa.py selftest
```

## Quick Start

```bash
# Start the daemon
python pad_pro.py &

# Reserve your first port
python pa.py run --name=myapp -- python -m http.server

# Access at https://myapp.pa.local
```

## What Gets Installed

| Component | Description |
|-----------|-------------|
| `pa` | CLI tool for port management |
| `pad` | Background daemon (auto-started) |
| `*.pa.local` | Local DNS resolution |
| TLS certificates | Auto-generated HTTPS |

## Verification

```bash
pa selftest
```

Expected output:
```
✅ Port Authority is ready!
   - Daemon: running (port 9999)
   - DNS: configured
   - TLS: ready
```
