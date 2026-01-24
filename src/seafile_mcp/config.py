"""Configuration management for Seafile MCP server.

This module handles loading and validating configuration from environment
variables, supporting both account-based and repository token authentication.
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator, model_validator


# Default size limits and timeout
DEFAULT_MAX_READ_SIZE = 1048576  # 1 MB
DEFAULT_MAX_WRITE_SIZE = 10485760  # 10 MB
DEFAULT_TIMEOUT = 30  # seconds


class SeafileConfig(BaseModel):
    """Configuration for Seafile MCP server.

    Supports two authentication modes:
    1. Account auth: Uses SEAFILE_USERNAME and SEAFILE_PASSWORD
    2. Repo token auth: Uses SEAFILE_REPO_TOKEN and SEAFILE_REPO_ID

    At least one authentication mode must be configured.
    """

    # Required
    server_url: str

    # Account authentication (optional, but one auth mode required)
    username: Optional[str] = None
    password: Optional[str] = None

    # Repository token authentication (optional, but one auth mode required)
    repo_token: Optional[str] = None
    repo_id: Optional[str] = None

    # Optional settings with defaults
    max_read_size: int = DEFAULT_MAX_READ_SIZE
    max_write_size: int = DEFAULT_MAX_WRITE_SIZE
    timeout: int = DEFAULT_TIMEOUT

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, v: str) -> str:
        """Validate and normalize the server URL."""
        if not v:
            raise ValueError("SEAFILE_SERVER_URL is required")
        # Remove trailing slash for consistency
        return v.rstrip("/")

    @field_validator("max_read_size", "max_write_size", "timeout")
    @classmethod
    def validate_positive_int(cls, v: int) -> int:
        """Ensure numeric settings are positive."""
        if v <= 0:
            raise ValueError("Value must be positive")
        return v

    @model_validator(mode="after")
    def validate_auth_mode(self) -> "SeafileConfig":
        """Validate that at least one authentication mode is configured."""
        has_account_auth = self.username is not None and self.password is not None
        has_repo_token_auth = self.repo_token is not None and self.repo_id is not None

        if not has_account_auth and not has_repo_token_auth:
            raise ValueError(
                "Invalid configuration: No authentication mode configured. "
                "Please provide either:\n"
                "  - Account auth: SEAFILE_USERNAME and SEAFILE_PASSWORD\n"
                "  - Repo token auth: SEAFILE_REPO_TOKEN and SEAFILE_REPO_ID"
            )

        # Warn if partial credentials are provided
        if self.username and not self.password:
            raise ValueError(
                "Invalid configuration: SEAFILE_USERNAME provided without SEAFILE_PASSWORD"
            )
        if self.password and not self.username:
            raise ValueError(
                "Invalid configuration: SEAFILE_PASSWORD provided without SEAFILE_USERNAME"
            )
        if self.repo_token and not self.repo_id:
            raise ValueError(
                "Invalid configuration: SEAFILE_REPO_TOKEN provided without SEAFILE_REPO_ID"
            )
        if self.repo_id and not self.repo_token:
            raise ValueError(
                "Invalid configuration: SEAFILE_REPO_ID provided without SEAFILE_REPO_TOKEN"
            )

        return self

    @property
    def has_account_auth(self) -> bool:
        """Check if account authentication is configured."""
        return self.username is not None and self.password is not None

    @property
    def has_repo_token_auth(self) -> bool:
        """Check if repository token authentication is configured."""
        return self.repo_token is not None and self.repo_id is not None

    @classmethod
    def from_env(cls) -> "SeafileConfig":
        """Load configuration from environment variables.

        Environment variables:
            SEAFILE_SERVER_URL: Required. The Seafile server URL.
            SEAFILE_USERNAME: Username for account authentication.
            SEAFILE_PASSWORD: Password for account authentication.
            SEAFILE_REPO_TOKEN: Repository access token.
            SEAFILE_REPO_ID: Repository ID for token authentication.
            SEAFILE_MAX_READ_SIZE: Maximum file size for reading (default: 1MB).
            SEAFILE_MAX_WRITE_SIZE: Maximum file size for writing (default: 10MB).
            SEAFILE_TIMEOUT: Request timeout in seconds (default: 30).

        Returns:
            SeafileConfig: Validated configuration instance.

        Raises:
            ValueError: If configuration is invalid.
        """
        # Load .env file if present
        load_dotenv()

        def get_int_env(key: str, default: int) -> int:
            """Get an integer environment variable with a default."""
            value = os.getenv(key)
            if value is None:
                return default
            try:
                return int(value)
            except ValueError:
                raise ValueError(f"{key} must be a valid integer, got: {value}")

        server_url = os.getenv("SEAFILE_SERVER_URL")
        if not server_url:
            raise ValueError(
                "SEAFILE_SERVER_URL environment variable is required. "
                "Please set it to your Seafile server URL (e.g., https://seafile.example.com)"
            )

        return cls(
            server_url=server_url,
            username=os.getenv("SEAFILE_USERNAME"),
            password=os.getenv("SEAFILE_PASSWORD"),
            repo_token=os.getenv("SEAFILE_REPO_TOKEN"),
            repo_id=os.getenv("SEAFILE_REPO_ID"),
            max_read_size=get_int_env("SEAFILE_MAX_READ_SIZE", DEFAULT_MAX_READ_SIZE),
            max_write_size=get_int_env("SEAFILE_MAX_WRITE_SIZE", DEFAULT_MAX_WRITE_SIZE),
            timeout=get_int_env("SEAFILE_TIMEOUT", DEFAULT_TIMEOUT),
        )


# Singleton configuration instance
_config: Optional[SeafileConfig] = None


def get_config() -> SeafileConfig:
    """Get the singleton configuration instance.

    Loads configuration from environment variables on first call.
    Subsequent calls return the cached instance.

    Returns:
        SeafileConfig: The validated configuration.

    Raises:
        ValueError: If configuration is invalid.
    """
    global _config
    if _config is None:
        _config = SeafileConfig.from_env()
    return _config


def reset_config() -> None:
    """Reset the singleton configuration instance.

    Useful for testing or reloading configuration.
    """
    global _config
    _config = None
