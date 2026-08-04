FROM python:3.13-slim AS builder

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir --target=/install ".[http]"


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

# stdio stays the default so `docker run -i` keeps working unchanged. For a network deployment
# set MAILCHIMP_TRANSPORT=streamable-http and MAILCHIMP_HOST=0.0.0.0 (the code defaults to
# loopback, which is unreachable from outside the container) and publish this port.
EXPOSE 8000

ENTRYPOINT ["mailchimp-mcp-server"]
