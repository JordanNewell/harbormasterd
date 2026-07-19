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
    content = f.read_text(encoding="utf-8").strip()
    if not content:
        # Empty/corrupted file — treat as missing, allow regeneration
        return None
    return content


def _write_file_token(token: str) -> None:
    f = _token_file_path()
    f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Re-assert dir mode in case it already existed with looser perms
    try:
        os.chmod(f.parent, stat.S_IRWXU)
    except OSError:
        pass
    # Open with mode 0600 directly — no TOCTOU window
    fd = os.open(str(f), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode("utf-8"))
    finally:
        os.close(fd)


def _read_keyring_token() -> Optional[str]:
    if not KEYRING_AVAILABLE:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except keyring.errors.KeyringError as exc:
        # Keyring backend error — log and treat as no token (regeneration will retry)
        import logging
        logging.getLogger("token_store").warning(
            "keyring read failed: %s; falling back to file token", exc
        )
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
