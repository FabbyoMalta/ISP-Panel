FROM node:24-alpine AS assets
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
COPY backend/templates/ /build/backend/templates/
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home portal
COPY --chown=portal:portal backend/ ./backend/
COPY --from=assets --chown=portal:portal /build/backend/static/ ./backend/static/
RUN DEBUG=true python backend/manage.py collectstatic --noinput
USER portal
EXPOSE 8000
CMD ["sh", "-c", "python backend/manage.py check_runtime_db && gunicorn --chdir backend config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60 --access-logfile - --access-logformat '%(s)s %(L)s'"]
