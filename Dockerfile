FROM python:3.13-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir --target=/install .


FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /install /usr/local/lib/python3.13/site-packages
COPY --from=builder /install/bin /usr/local/bin

RUN useradd --create-home --uid 1000 mcp \
    && chown -R mcp:mcp /app

USER mcp

ENV MAILCHIMP_API_KEY="" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["mailchimp-mcp-server"]
