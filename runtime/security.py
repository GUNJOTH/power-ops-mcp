"""MCP transport security helpers."""

from __future__ import annotations

import hmac

from mcp.server.auth.provider import AccessToken


class StaticTokenVerifier:
    """Verify a deployment-scoped bearer token without logging its value."""

    def __init__(self, expected_token: str) -> None:
        self._expected = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not self._expected or not hmac.compare_digest(token, self._expected):
            return None
        return AccessToken(
            token=token,
            client_id="dify-power-operations",
            subject="dify-power-operations",
            scopes=["mcp:tools"],
        )
