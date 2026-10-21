"""No credential may have a default in code, and production refuses to start without its keys."""

from __future__ import annotations

import secrets
from urllib.parse import quote

import pytest

from cairn.config import ConfigError, Settings

CREDENTIAL_FIELDS = ("database_url", "admin_database_url", "secret_key", "master_key")


def test_credentials_have_no_default_values():
    for name in CREDENTIAL_FIELDS:
        assert Settings.model_fields[name].default is None, f"{name} must not have a default"


def test_missing_database_url_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("CAIRN_DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    with pytest.raises(ConfigError, match="CAIRN_DATABASE_URL"):
        _ = s.app_db_url


def test_production_requires_explicit_keys(monkeypatch, tmp_path):
    for k in ("CAIRN_SECRET_KEY", "CAIRN_MASTER_KEY"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None, env="production", dev_key_file=str(tmp_path / "keys.json"))
    with pytest.raises(ConfigError, match="production"):
        _ = s.session_secret
    assert not (tmp_path / "keys.json").exists()


def test_development_keys_are_random_and_stable(monkeypatch, tmp_path):
    for k in ("CAIRN_SECRET_KEY", "CAIRN_MASTER_KEY"):
        monkeypatch.delenv(k, raising=False)
    path = tmp_path / "keys.json"
    a = Settings(_env_file=None, dev_key_file=str(path))
    b = Settings(_env_file=None, dev_key_file=str(path))
    other = Settings(_env_file=None, dev_key_file=str(tmp_path / "other.json"))
    assert a.session_secret == b.session_secret and a.encryption_master_key == b.encryption_master_key
    assert a.session_secret != other.session_secret
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_app_role_password_comes_from_the_url():
    pw = secrets.token_urlsafe(12) + "@/"  # characters that need URL-encoding
    s = Settings(_env_file=None, database_url=f"postgresql://cairn_app:{quote(pw, safe='')}@db:5432/cairn")
    assert s.app_role_password == pw
    assert Settings(_env_file=None, database_url="postgresql://cairn_app@db/cairn").app_role_password is None
