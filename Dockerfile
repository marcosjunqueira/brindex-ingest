# syntax=docker/dockerfile:1

# Build stage: build a wheel so the runtime image carries no build tooling or source tree.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src src
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BRINDEX_DB_PATH=/data/brindex.sqlite
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
# Fixed non-root uid/gid shared by every brindex image, so files on the shared data volume keep one
# owner. Compose can override it with `user:` to match the host user that owns ./data.
RUN groupadd -g 10001 brindex && useradd -u 10001 -g brindex -M -s /usr/sbin/nologin brindex \
    && mkdir /data && chown brindex:brindex /data
# The SQLite file is mounted here at runtime; this job is its only writer.
VOLUME /data
USER brindex
WORKDIR /data
# One-shot job: runs one ingestion and exits (non-zero if any source failed). No healthcheck.
# Arguments are passed through, e.g. `docker compose run --rm ingest --source ptax`.
ENTRYPOINT ["brindex-ingest"]
