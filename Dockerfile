# syntax=docker/dockerfile:1

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LC_AUTO_TEMPLATE_DIR=/opt/lc-auto/templates \
    LC_AUTO_INIT_CONFIG_TEMPLATE=config.docker.example.yaml

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY lc_auto ./lc_auto
COPY config.example.yaml config.fake.yaml config.docker.example.yaml .env.example problems.txt /opt/lc-auto/templates/

RUN pip install --upgrade pip \
    && pip install .

WORKDIR /data

ENTRYPOINT ["python", "-m", "lc_auto"]
CMD ["--help"]
