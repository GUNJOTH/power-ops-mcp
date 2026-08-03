FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:5d275ca5f0da33c3368ac8fbb85fafabad023b3b8a7cff39a94ac0baecfd9a50

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app.py ./
COPY generated ./generated
COPY runtime ./runtime

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin mcp \
    && chown -R mcp:mcp /app
USER 10001:10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD [".venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"]
CMD [".venv/bin/python", "app.py"]
