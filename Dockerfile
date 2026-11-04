FROM python:3.11-slim-bookworm@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd AS python

FROM python AS builder
WORKDIR /source
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/
RUN pip install --no-cache-dir uv==0.12.17 \
    && uv build --wheel --out-dir /wheel \
    && uv export --locked --no-default-groups --no-emit-project -o /tmp/core.txt \
    && uv export --locked --no-default-groups --no-emit-project --extra all -o /tmp/ui.txt

FROM builder AS dependencies
RUN uv venv /opt/etl-craft \
    && uv pip install --python /opt/etl-craft/bin/python --no-cache --compile-bytecode --require-hashes -r /tmp/core.txt \
    && uv pip install --python /opt/etl-craft/bin/python --no-cache --compile-bytecode --no-deps /wheel/*.whl

FROM dependencies AS web
RUN uv pip install --python /opt/etl-craft/bin/python --no-cache --compile-bytecode --require-hashes -r /tmp/ui.txt

FROM python AS runtime
LABEL org.opencontainers.image.source="https://github.com/etl-craft/etl-craft"
ENV PATH="/opt/etl-craft/bin:$PATH" \
    HOME=/state \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN python -m pip uninstall --yes setuptools wheel pip \
    && rm -rf /usr/local/lib/python3.11/ensurepip/_bundled \
    && groupadd --gid 10001 craft \
    && useradd --uid 10001 --gid craft --home-dir /state craft \
    && install -d -o craft -g craft /project /state
WORKDIR /project
VOLUME ["/project", "/state", "/tmp"]
USER 10001:10001
ENTRYPOINT ["etl-craft"]

FROM runtime AS base
COPY --from=dependencies /opt/etl-craft /opt/etl-craft

FROM runtime AS ui
COPY --from=web /opt/etl-craft /opt/etl-craft
