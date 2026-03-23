# Synaptica Research Agents
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY agents/ ./agents/
COPY shared/ ./shared/

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 5001

CMD ["uv", "run", "python", "-m", "uvicorn", "agents.research.main:app", "--host", "0.0.0.0", "--port", "5001", "--proxy-headers", "--forwarded-allow-ips", "*"]
