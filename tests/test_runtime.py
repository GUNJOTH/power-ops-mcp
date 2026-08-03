import asyncio
import os
from pathlib import Path
import subprocess
import sys
import pytest

from runtime.config import get_settings
from runtime.security import StaticTokenVerifier


ROOT = Path(__file__).resolve().parents[1]


def test_production_requires_auth_when_listening_on_all_interfaces(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_REQUIRE_AUTH", "false")
    monkeypatch.setenv("MYSQL_USER", "reader")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="必须启用 MCP 鉴权"):
        get_settings().validate_startup()
    get_settings.cache_clear()


def test_static_token_verifier_accepts_only_exact_token():
    verifier = StaticTokenVerifier("correct-token")
    accepted = asyncio.run(verifier.verify_token("correct-token"))
    rejected = asyncio.run(verifier.verify_token("wrong-token"))
    assert accepted is not None
    assert accepted.client_id == "dify-power-operations"
    assert rejected is None


def test_authenticated_fastmcp_application_constructs():
    env = os.environ.copy()
    env.update({
        "MCP_REQUIRE_AUTH": "true",
        "MCP_AUTH_TOKEN": "test-token-not-default",
        "MYSQL_USER": "reader",
        "MYSQL_PASSWORD": "secret",
    })
    code = """
import app
from starlette.testclient import TestClient
headers = {
    'host': 'localhost:8000',
    'content-type': 'application/json',
    'accept': 'application/json, text/event-stream',
}
body = {
    'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
    'params': {
        'protocolVersion': '2025-06-18', 'capabilities': {},
        'clientInfo': {'name': 'security-test', 'version': '1'},
    },
}
with TestClient(app.MCP.streamable_http_app()) as client:
    assert client.post('/mcp', headers=headers, json=body).status_code == 401
    headers['authorization'] = 'Bearer test-token-not-default'
    assert client.post('/mcp', headers=headers, json=body).status_code == 200
print('AUTH_APP_OK')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "AUTH_APP_OK" in result.stdout
