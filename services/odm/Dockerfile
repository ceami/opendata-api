FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    tzdata \
    wget \
    curl \
    git \
    vim \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/program

WORKDIR /opt/program
COPY ./pyproject.toml /opt/program/pyproject.toml

RUN uv lock && uv venv && uv sync --frozen --no-cache --no-dev

COPY ./src /opt/program

ENV PYTHONPATH=/opt/program
