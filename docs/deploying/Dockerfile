ARG BASE_IMAGE
FROM ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc AS uv
FROM ${BASE_IMAGE} AS dependencies
USER root
ARG ETL_CRAFT_REQUIREMENT
COPY --from=uv /uv /tmp/uv
COPY wheels/ /tmp/wheels/
RUN if [ -n "$ETL_CRAFT_REQUIREMENT" ]; then \
      /tmp/uv pip install --python /opt/etl-craft/bin/python --no-cache --link-mode=copy \
        --find-links /tmp/wheels "$ETL_CRAFT_REQUIREMENT"; \
    fi
FROM ${BASE_IMAGE}
COPY --from=dependencies /opt/etl-craft /opt/etl-craft
COPY --chown=10001:10001 project/ /project/
