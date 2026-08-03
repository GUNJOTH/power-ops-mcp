# Security policy

Do not commit `.env`, database credentials, MCP bearer tokens, Dify secrets,
query results, or production logs.

Production requirements:

- `MCP_REQUIRE_AUTH=true`
- private network or localhost-only published port
- TLS at the reverse proxy/API gateway
- Origin and Host allowlists
- read-only database account scoped to governed views
- non-root, read-only container with dropped Linux capabilities
- secret rotation and dependency/image scanning

Report suspected exposure by immediately rotating the affected secret,
preserving audit evidence, and notifying the project owner. Do not include live
secrets in an issue or chat transcript.
