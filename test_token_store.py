"""Unit tests for token_store."""
import os
import stat
import pytest
from unittest.mock import patch

from token_store import (
    get_or_create_token,
    get_token,
    TOKEN_ENV_VAR,
    _token_file_path,
)


def test_get_or_create_token_returns_env_var_when_set(monkeypatch):
    """Env var always wins."""
    monkeypatch.setenv(TOKEN_ENV_VAR, "env-token-12345")
    assert get_or_create_token() == "env-token-12345"


def test_get_or_create_token_persists_across_calls(tmp_path):
    """First call creates, second call reads same value.

    Keyring mock simulates real backend: set_password stores into a dict
    that get_password reads back. Without this, the second call sees no
    stored token and generates a new one, defeating the persistence check.
    """
    token_file = tmp_path / "daemon.token"
    store = {}
    # keyring API: get_password(service, user) -> str|None
    #              set_password(service, user, password) -> None
    def _get(*args):
        return store.get("token")
    def _set(*args):
        store["token"] = args[2]
    with patch("token_store._token_file_path", return_value=token_file), \
         patch("token_store.keyring") as mock_keyring, \
         patch("token_store.KEYRING_AVAILABLE", True):
        mock_keyring.get_password.side_effect = _get
        mock_keyring.set_password.side_effect = _set
        first = get_or_create_token()
        second = get_or_create_token()
    assert first == second
    assert len(first) >= 32  # secrets.token_hex(32) = 64 chars


def test_get_token_returns_none_when_no_token(monkeypatch, tmp_path):
    """Read-only path returns None when nothing is stored."""
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    token_file = tmp_path / "daemon.token"
    with patch("token_store._token_file_path", return_value=token_file), \
         patch("token_store.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        assert get_token() is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes do not apply to Windows NTFS")
def test_token_file_is_mode_600_on_posix(tmp_path):
    """File fallback must be mode 600 on POSIX systems."""
    token_file = tmp_path / "daemon.token"
    with patch("token_store._token_file_path", return_value=token_file), \
         patch("token_store.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        mock_keyring.set_password.side_effect = Exception("no keyring backend")
        get_or_create_token()
    assert token_file.exists()
    mode = stat.S_IMODE(token_file.stat().st_mode)
    assert mode == 0o600


def test_token_file_is_created_on_windows(tmp_path):
    """On Windows, file fallback creates the file (mode check skipped)."""
    if os.name != "nt":
        pytest.skip("Windows-specific test")
    token_file = tmp_path / "daemon.token"
    with patch("token_store._token_file_path", return_value=token_file), \
         patch("token_store.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        mock_keyring.set_password.side_effect = Exception("no keyring backend")
        get_or_create_token()
    assert token_file.exists()
    # File should be readable (contents are the token)
    assert len(token_file.read_text()) >= 32


def test_empty_token_file_treated_as_missing(monkeypatch, tmp_path):
    """Empty token file should be treated as missing, not as valid empty token."""
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    token_file = tmp_path / "daemon.token"
    token_file.write_text("")
    with patch("token_store._token_file_path", return_value=token_file), \
         patch("token_store.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        mock_keyring.set_password.return_value = None
        # Should regenerate (not return empty string)
        result = get_or_create_token()
    assert result and len(result) >= 32
