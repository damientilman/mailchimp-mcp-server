FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

ENV MAILCHIMP_API_KEY=""

ENTRYPOINT ["mailchimp-mcp-server"]
