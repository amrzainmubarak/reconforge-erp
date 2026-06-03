FROM python:3.11-slim@sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml setup.py README.md LICENSE requirements.txt requirements-runtime.lock ./
COPY reconforge ./reconforge
COPY config ./config
COPY examples ./examples
COPY control-packs ./control-packs
COPY docs ./docs

RUN python -m pip install --no-cache-dir --require-hashes -r requirements-runtime.lock \
    && python -m pip install --no-cache-dir --no-deps --no-build-isolation -e .

CMD ["reconforge", "doctor"]
