"""Runtime settings, read from the environment (prefix CAIRN_).

No credential has a default value in code. Database URLs must come from the
environment (or a local, gitignored ``.env``). The session-signing key and the
envelope-encryption master key must be set in production; in development they
are generated once and kept in a local, gitignored key file so sessions and
encrypted tool credentials survive restarts.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from functools import cached_property, lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("cairn.config")


class ConfigError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAIRN_", env_file=".env", extra="ignore")

    env: str = Field(default="development", pattern="^(development|test|production)$")

    # The app role is subject to row-level security. The admin URL is used
    # only for migrations, tenant provisioning and the job queue claim.
    database_url: str | None = None
    admin_database_url: str | None = None

    # Set both in production. Development falls back to a generated key file.
    secret_key: str | None = None
    master_key: str | None = None  # base64 of 32 bytes; wraps per-secret data keys
    dev_key_file: str = ".cairn-dev-keys.json"

    # "auto" uses Claude when ANTHROPIC_API_KEY is set and the sandbox model otherwise.
    model_mode: str = Field(default="auto", pattern="^(auto|sandbox|anthropic)$")

    public_url: str = "http://localhost:8000"
    console_url: str = "http://localhost:3000"
    cors_origins: str = "*"

    run_worker: bool = True
    worker_poll_seconds: float = 1.0

    session_ttl_hours: int = 12
    cookie_secure: bool = False

    dkim_selector: str = "cairn"
    dkim_private_key_path: str | None = None
    smtp_url: str | None = None

    # ------------------------------------------------------------ database

    def _required(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise ConfigError(f"CAIRN_{name.upper()} is not set. Copy .env.example to .env "
                              "(or run scripts/gen-env.sh) and fill it in.")
        return value

    @property
    def app_db_url(self) -> str:
        return self._required("database_url")

    @property
    def admin_db_url(self) -> str:
        return self._required("admin_database_url")

    @property
    def app_role_password(self) -> str | None:
        """The app role's password is whatever its connection URL carries."""
        pw = urlsplit(self.app_db_url).password
        return unquote(pw) if pw else None

    # ---------------------------------------------------------------- keys

    @cached_property
    def _dev_keys(self) -> dict[str, str]:
        if self.env == "production":
            raise ConfigError("CAIRN_SECRET_KEY and CAIRN_MASTER_KEY must be set in production.")
        path = Path(self.dev_key_file)
        try:
            data = json.loads(path.read_text())
            if data.get("secret_key") and data.get("master_key"):
                return data
        except (OSError, ValueError):
            pass
        data = {"secret_key": secrets.token_urlsafe(48),
                "master_key": base64.b64encode(secrets.token_bytes(32)).decode()}
        try:
            path.write_text(json.dumps(data))
            path.chmod(0o600)
            log.warning("Generated development keys in %s. Set CAIRN_SECRET_KEY and CAIRN_MASTER_KEY "
                        "for any shared or production deployment.", path.resolve())
        except OSError:
            log.warning("Using ephemeral development keys; sessions and stored credentials will not "
                        "survive a restart.")
        return data

    @property
    def session_secret(self) -> str:
        return self.secret_key or self._dev_keys["secret_key"]

    @property
    def encryption_master_key(self) -> str:
        return self.master_key or self._dev_keys["master_key"]

    # -------------------------------------------------------------- models

    @property
    def anthropic_available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    @property
    def use_claude(self) -> bool:
        if self.model_mode == "sandbox":
            return False
        if self.model_mode == "anthropic":
            return True
        return self.anthropic_available


@lru_cache
def get_settings() -> Settings:
    return Settings()
