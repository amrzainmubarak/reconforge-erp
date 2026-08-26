# syntax=docker/dockerfile:1.7
FROM python:3.11-alpine@sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1 AS builder

# The pinned Python index is intentionally retained, but Alpine security
# packages must be refreshed independently of the slower Python image cadence.
# Keep the builder inside the same fixed-component boundary as the runtime and
# fail closed if the reviewed fixed package version is unavailable.
RUN apk add --no-cache --upgrade \
    libcrypto3=3.5.8-r0 \
    libssl3=3.5.8-r0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

ADD --checksum=sha256:1fd052f196108d87e61fc3d98fe06b4ec758c9a1eb1466a6fd1a436fe45885f2 https://github.com/astral-sh/uv/releases/download/0.11.32/uv-x86_64-unknown-linux-musl.tar.gz /tmp/uv.tar.gz
RUN mkdir /tmp/uv \
    && tar --extract --gzip --file /tmp/uv.tar.gz --directory /tmp/uv --strip-components=1 \
    && install -m 0755 /tmp/uv/uv /usr/local/bin/uv \
    && install -m 0755 /tmp/uv/uvx /usr/local/bin/uvx \
    && uv --version | grep -Eq '^uv 0\.11\.32( |$)' \
    && rm -rf /tmp/uv /tmp/uv.tar.gz

COPY pyproject.toml uv.lock setup.py README.md LICENSE ./
COPY reconforge ./reconforge
COPY config ./config
COPY examples ./examples
COPY control-packs ./control-packs
COPY alembic.ini .
COPY alembic ./alembic

RUN uv sync --locked --no-dev --no-editable --python 3.11 --link-mode copy \
    && rm -rf /root/.cache/uv

FROM python:3.11-alpine@sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1 AS runtime

# The official index can lag an Alpine security fix. Install only the named,
# reviewed OpenSSL runtime versions so the final image contains the fixed
# packages without adding the OpenSSL CLI to the trimmed runtime.
RUN apk add --no-cache --upgrade \
    libcrypto3=3.5.8-r0 \
    libssl3=3.5.8-r0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN rm -rf /usr/local/lib/python3.11/site-packages/* \
    /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.11 \
    && addgroup -g 10001 -S reconforge \
    && adduser -u 10001 -S -D -H -G reconforge -s /sbin/nologin reconforge \
    && mkdir -p /app/output /data \
    && chown 10001:10001 /app/output /data

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/config /app/config
COPY --from=builder /app/examples /app/examples
COPY --from=builder /app/control-packs /app/control-packs
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/alembic /app/alembic

USER 10001:10001

CMD ["reconforge", "doctor"]
