FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml setup.py ./
COPY gauntlet/ gauntlet/

RUN pip install --no-cache-dir . \
    && adduser --disabled-password --no-create-home gauntlet

USER gauntlet

EXPOSE 8484

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8484/health', timeout=3)" || exit 1

CMD ["gauntlet", "mcp", "-t", "streamable-http", "--host", "0.0.0.0", "-p", "8484"]
