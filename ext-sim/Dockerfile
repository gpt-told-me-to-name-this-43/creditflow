# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.21 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.12-slim AS runtime
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY app ./app
COPY fixtures ./fixtures
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
# Доступ-лог uvicorn отключён: запросы логирует middleware без тел и query-строки.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
