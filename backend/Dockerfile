FROM ghcr.io/astral-sh/uv:0.12.11 AS uv

FROM python:3.14-slim AS build

ENV UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=uv /uv /uvx /bin/
WORKDIR /workspace/backend
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libpq5 \
    && groupadd --system --gid 10001 portal \
    && useradd --system --uid 10001 --gid portal --create-home portal \
    && rm -rf /var/lib/apt/lists/* \
        /usr/local/lib/python*/ensurepip \
        /usr/local/lib/python*/site-packages/pip \
        /usr/local/lib/python*/site-packages/pip-*.dist-info \
        /usr/local/bin/pip*

WORKDIR /workspace/backend
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY ops ./ops

USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
