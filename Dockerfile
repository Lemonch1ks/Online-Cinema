FROM python:3.14-slim

# Print logs immediately, do not write .pyc files.
# Poetry installs straight into the image's Python: the container is already isolated, no venv needed.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=2.5.1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root && rm -rf /root/.cache/pypoetry

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
