FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
USER 65534:65534
ENTRYPOINT ["opendata-collect"]
CMD ["--help"]
