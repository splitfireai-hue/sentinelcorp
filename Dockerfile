FROM python:3.11-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install . && \
    pip install --no-cache-dir --prefix=/install gunicorn greenlet asyncpg

FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

RUN rm -rf tests/ .env .env.example .gitignore sdk/ docker-compose.yml

RUN mkdir -p /app/data && chmod 777 /app/data

ENV PORT=8000
ENV DATABASE_URL=sqlite+aiosqlite:////app/data/sentinelcorp.db
ENV ENVIRONMENT=production
ENV FREE_TIER_ENABLED=true
ENV FREE_TIER_REQUESTS=1000
ENV ADMIN_SECRET=""

CMD python -m app.data.seed_debarred || echo "Seed skipped" ; \
    python -m gunicorn app.main:app \
        --worker-class uvicorn.workers.UvicornWorker \
        --bind 0.0.0.0:$PORT \
        --workers 1 \
        --timeout 60 \
        --access-logfile - \
        --error-logfile -
