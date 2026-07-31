# syntax=docker/dockerfile:1.7
FROM python:3.11-slim@sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

ADD --checksum=sha256:aab924fd522efd06f1c5f3b93a243864fc453132c94b2dc49f1371b528a4b967 https://github.com/astral-sh/uv/releases/download/0.11.32/uv-x86_64-unknown-linux-gnu.tar.gz /tmp/uv.tar.gz
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
COPY docs ./docs
COPY alembic.ini .
COPY alembic ./alembic

RUN uv sync --locked --no-dev --no-editable --python 3.11 --link-mode copy \
    && rm -rf /root/.cache/uv

ENV PATH="/app/.venv/bin:$PATH"

CMD ["reconforge", "doctor"]
