# syntax=docker/dockerfile:1.7
FROM python:3.14-alpine@sha256:3f818d6811ff5f3f2b5e5d836df3d25c2dd2e588d3b4981338a8ba17e422f74f AS builder

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

FROM python:3.14-alpine@sha256:3f818d6811ff5f3f2b5e5d836df3d25c2dd2e588d3b4981338a8ba17e422f74f AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN rm -rf /usr/local/lib/python3.11/site-packages/* \
    /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.11 \
    && addgroup -g 10001 -S reconforge \
    && adduser -u 10001 -S -D -H -G reconforge -s /sbin/nologin reconforge \
    && mkdir -p /app/output \
    && chown 10001:10001 /app/output

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/config /app/config
COPY --from=builder /app/examples /app/examples
COPY --from=builder /app/control-packs /app/control-packs
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/alembic /app/alembic

USER 10001:10001

CMD ["reconforge", "doctor"]
