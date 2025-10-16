"""Configuration helpers for the FastAPI backend.

This module centralises runtime configuration. All secrets are expected to be
provided via the operating system keyring or environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Final


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class SecurityConfig:
    """Security-sensitive configuration options.

    Attributes:
        hmac_secret_env_var: Name of the environment variable that stores the
            hex-encoded HMAC key for request signing. The actual key value must
            be managed outside of source control to avoid leaking secrets.
        nonce_ttl_seconds: Number of seconds a nonce is considered valid.
    """

    hmac_secret_env_var: str = "SEO_AUDITOR_HMAC_SECRET"
    nonce_ttl_seconds: int = 30 * 60  # 30 minutes, aligns with PRD rotation rules.


SECURITY_CONFIG: Final = SecurityConfig()


def load_hmac_secret(*, env_var: str | None = None) -> bytes:
    """Load the HMAC signing secret from the environment.

    Args:
        env_var: Optional override for the environment variable name. Defaults
            to :data:`SecurityConfig.hmac_secret_env_var`.

    Returns:
        The raw bytes of the HMAC key.

    Raises:
        ConfigurationError: If the secret is missing or improperly formatted.
    """

    key_var = env_var or SECURITY_CONFIG.hmac_secret_env_var
    secret_hex = os.environ.get(key_var)
    if secret_hex is None:
        msg = (
            "HMAC signing secret missing. Set the environment variable "
            f"{key_var} using a secure keyring integration."
        )
        raise ConfigurationError(msg)

    try:
        secret = bytes.fromhex(secret_hex)
    except ValueError as exc:  # input validation prevents using malformed secrets
        raise ConfigurationError("HMAC signing secret must be hex-encoded.") from exc

    if len(secret) < 32:
        raise ConfigurationError("HMAC signing secret must be at least 32 bytes.")

    return secret
