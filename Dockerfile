FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY gauntlet/ gauntlet/

RUN pip install --no-cache-dir .

ENV PORT=8484
EXPOSE 8484

CMD ["gauntlet", "mcp", "-t", "streamable-http", "--host", "0.0.0.0", "-p", "8484"]
