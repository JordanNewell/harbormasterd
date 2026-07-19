"""Unit tests for token_store."""
import os
import pytest
from pathlib import Path
from unittest.mock import patch
import tempfile

from token_store import get_or_create_token, get_token, TOKEN_ENV_VAR


def test_get_or_create_token_returns_env_var_when_set(monkeypatch, tmp_path):
    """Env var always wins."""
    monkeypatch.setenv(TOKEN_ENV_VAR, "env-token-12345")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_or_create_token() == "env-token-12345"


def test_get_or_create_token_persists_across_calls(monkeypatch, tmp_path):
    """First call creates, second call reads same value."""
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    with patch("token_store.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        mock_keyring.set_password.return_value = None
        first = get_or_create_token()
        second = get_or_create_token()
    assert first == second
    assert len(first) >= 32  # secrets.token_hex(32) = 64 chars


def test_get_token_returns_none_when_no_token(monkeypatch, tmp_path):
    """Read-only path returns None when nothing is stored."""
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    with patch("token_store.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        assert get_token() is None


def test_token_file_is_mode_600(monkeypatch, tmp_path):
    """File fallback must be mode 600."""
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    with patch("token_store.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        mock_keyring.set_password.side_effect = Exception("no keyring backend")
        get_or_create_token()
    token_file = tmp_path / ".port-authority" / "daemon.token"
    assert token_file.exists()
    mode = oct(token_file.stat().st_mode)[-3:]
    assert mode == "600"
