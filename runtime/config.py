"""Typed environment configuration with explicit production validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必须是 true/false")


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _list(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    environment: str
    service_version: str
    mcp_host: str
    mcp_port: int
    mcp_transport: str
    auth_required: bool
    auth_token: str
    auth_issuer_url: str
    public_url: str
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    max_request_body_size: int
    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str
    mysql_connect_timeout: int
    mysql_read_timeout: int
    mysql_statement_timeout_ms: int
    mysql_pool_size: int
    mysql_pool_wait_seconds: int
    max_concurrent_queries: int
    fuzzy_min_length: int
    log_level: str

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    def validate_startup(self) -> None:
        missing = [
            name for name, value in (
                ("MYSQL_USER", self.mysql_user),
                ("MYSQL_PASSWORD", self.mysql_password),
            ) if not value
        ]
        if missing:
            raise ValueError("缺少必填环境变量: " + ", ".join(missing))
        if self.auth_required and (not self.auth_token or self.auth_token == "replace_me"):
            raise ValueError("MCP_REQUIRE_AUTH=true 时必须配置非默认 MCP_AUTH_TOKEN")
        if self.is_production and self.mcp_host == "0.0.0.0" and not self.auth_required:
            raise ValueError("生产环境监听 0.0.0.0 时必须启用 MCP 鉴权")
        if self.mcp_transport not in {"streamable-http", "sse", "stdio"}:
            raise ValueError("MCP_TRANSPORT 仅支持 streamable-http、sse 或 stdio")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        environment=os.getenv("APP_ENV", "development"),
        service_version=os.getenv("SERVICE_VERSION", "0.2.0"),
        mcp_host=os.getenv("MCP_HOST", "127.0.0.1"),
        mcp_port=_int("MCP_PORT", 8000, 1, 65535),
        mcp_transport=os.getenv("MCP_TRANSPORT", "streamable-http"),
        auth_required=_bool("MCP_REQUIRE_AUTH", False),
        auth_token=os.getenv("MCP_AUTH_TOKEN", ""),
        auth_issuer_url=os.getenv("MCP_AUTH_ISSUER_URL", "http://localhost:8000"),
        public_url=os.getenv("MCP_PUBLIC_URL", "http://localhost:8000"),
        allowed_hosts=_list(
            "MCP_ALLOWED_HOSTS",
            "127.0.0.1:*,localhost:*,host.docker.internal:*,power-ops-mcp:*",
        ),
        allowed_origins=_list("MCP_ALLOWED_ORIGINS", ""),
        max_request_body_size=_int("MCP_MAX_REQUEST_BODY_SIZE", 1_048_576, 16_384, 16_777_216),
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        mysql_port=_int("MYSQL_PORT", 3306, 1, 65535),
        mysql_database=os.getenv("MYSQL_DATABASE", "sqldemo3"),
        mysql_user=os.getenv("MYSQL_USER", ""),
        mysql_password=os.getenv("MYSQL_PASSWORD", ""),
        mysql_connect_timeout=_int("MYSQL_CONNECT_TIMEOUT", 10, 1, 120),
        mysql_read_timeout=_int("MYSQL_READ_TIMEOUT", 30, 1, 300),
        mysql_statement_timeout_ms=_int("MYSQL_STATEMENT_TIMEOUT_MS", 25_000, 100, 300_000),
        mysql_pool_size=_int("MYSQL_POOL_SIZE", 8, 1, 64),
        mysql_pool_wait_seconds=_int("MYSQL_POOL_WAIT_SECONDS", 3, 1, 60),
        max_concurrent_queries=_int("MCP_MAX_CONCURRENT_QUERIES", 8, 1, 64),
        fuzzy_min_length=_int("MCP_FUZZY_MIN_LENGTH", 2, 1, 20),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
