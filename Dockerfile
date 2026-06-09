FROM node:22-bookworm-slim AS frontend

WORKDIR /app/front-end
COPY front-end/package*.json ./
RUN npm ci
COPY front-end/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAA_CONFIG_PATH=/app/config/watch_profiles.yaml \
    DAA_DB_PATH=/app/data/articles.sqlite \
    DAA_CONTENT_DIR=/app/content \
    DAA_TIMEZONE=UTC

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

COPY config/watch_profiles.yaml ./config/watch_profiles.yaml
COPY --from=frontend /app/front-end/dist ./front-end/dist

RUN mkdir -p /app/config /app/data /app/content/daily /app/content/weekly /app/content/readings

EXPOSE 8000

CMD ["uvicorn", "dailyarticleagent.web:app", "--host", "0.0.0.0", "--port", "8000"]
