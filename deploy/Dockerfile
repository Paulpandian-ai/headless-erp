# Build from the repository root:  docker build -f deploy/Dockerfile .
# (flyctl: `flyctl deploy . --config deploy/fly.toml --dockerfile deploy/Dockerfile`)
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
# 1. Dependency-only layer (cached until pyproject.toml / uv.lock change). README.md is copied
#    here too because the project metadata (hatchling) reads it.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
# 2. Project layer: the package itself needs src/ (and README.md from above) to build.
COPY src ./src
COPY policies ./policies
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" ANERP_PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["anerp", "serve"]
