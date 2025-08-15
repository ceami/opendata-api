FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/program

WORKDIR /opt/program
COPY ./pyproject.toml /opt/program/pyproject.toml

RUN uv lock && uv venv && uv sync --frozen --no-cache --no-dev

COPY ./src /opt/program
