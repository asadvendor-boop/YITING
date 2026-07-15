FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md ./
COPY shared ./shared
COPY gateway ./gateway
COPY agents ./agents
COPY victim-app ./victim-app
COPY docker/entrypoint.sh /usr/local/bin/yiting-entrypoint

RUN uv sync --locked --no-dev \
    && chmod 0755 /usr/local/bin/yiting-entrypoint

EXPOSE 8000 9000

ENTRYPOINT ["yiting-entrypoint"]
CMD ["gateway"]
