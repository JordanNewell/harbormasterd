#!/bin/bash
# Harbormasterd One-Line Install Script
# Usage: curl -sSf https://install.harbormasterd.dev | sh

set -e

INSTALL_DIR="$HOME/.harbormasterd"
VENV_DIR="$INSTALL_DIR/venv"
REPO_URL="https://github.com/JordanNewell/harbormasterd"

echo "🚢 Installing Harbormasterd..."
echo ""

# Detect OS
OS="$(uname -s)"
case "${OS}" in
    Linux*)     MACHINE=Linux;;
    Darwin*)    MACHINE=Mac;;
    MINGW*)     MACHINE=Windows;;
    *)          MACHINE="UNKNOWN:${OS}"
esac

echo "📦 Detected platform: $MACHINE"

# Check Python 3.9+
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3.9+ required but not found"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
echo "🐍 Found Python $PYTHON_VERSION"

# Create install directory
echo "📁 Installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# Create virtual environment
echo "🔧 Setting up virtual environment..."
python3 -m venv "$VENV_DIR"

# Activate and install
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install harbormasterd

# Add to PATH (bash/zsh)
SHELL_CONFIG="$HOME/.bashrc"
if [ -n "$ZSH_VERSION" ]; then
    SHELL_CONFIG="$HOME/.zshrc"
fi

if ! grep -q 'harbormasterd' "$SHELL_CONFIG" 2>/dev/null; then
    echo ""
    echo "📝 Adding to PATH in $SHELL_CONFIG"
    echo "" >> "$SHELL_CONFIG"
    echo "# Harbormasterd" >> "$SHELL_CONFIG"
    echo "export PATH=\"\$HOME/.harbormasterd/venv/bin:\$PATH\"" >> "$SHELL_CONFIG"
fi

# Run selftest
echo ""
echo "🧪 Running installation check..."
pa selftest

echo ""
echo "✅ Harbormasterd installed!"
echo ""
echo "→ Start using: pa run --name=myapp -- <your-command>"
echo "→ Get help: pa --help"
echo "→ Docs: https://github.com/JordanNewell/harbormasterd"
echo ""
echo "🎉 Welcome aboard!"
