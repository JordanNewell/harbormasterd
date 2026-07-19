"""Secure admin token storage for Port Authority daemon.

Primary: system keyring.
Fallback: ~/.port-authority/daemon.token (mode 600).
Override: PAD_ADMIN_TOKEN environment variable always wins.
"""
import os
import secrets
import stat
from pathlib import Path
from typing import Optional

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

TOKEN_ENV_VAR = "PAD_ADMIN_TOKEN"
KEYRING_SERVICE = "port-authority"
KEYRING_USER = "daemon"


def _token_file_path() -> Path:
    return Path.home() / ".port-authority" / "daemon.token"


def _read_file_token() -> Optional[str]:
    f = _token_file_path()
    if not f.exists():
        return None
    return f.read_text().strip()


def _write_file_token(token: str) -> None:
    f = _token_file_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(token)
    os.chmod(f, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def _read_keyring_token() -> Optional[str]:
    if not KEYRING_AVAILABLE:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return None


def _write_keyring_token(token: str) -> None:
    if not KEYRING_AVAILABLE:
        raise RuntimeError("keyring not available")
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)


def get_token() -> Optional[str]:
    """Read existing token. Returns None if none exists. Does NOT create."""
    if os.environ.get(TOKEN_ENV_VAR):
        return os.environ[TOKEN_ENV_VAR]
    return _read_keyring_token() or _read_file_token()


def get_or_create_token() -> str:
    """Read existing token, or generate + persist a new one."""
    existing = get_token()
    if existing:
        return existing
    new_token = secrets.token_hex(32)
    try:
        _write_keyring_token(new_token)
    except Exception:
        _write_file_token(new_token)
    return new_token
