FROM python:3.13.11-slim@sha256:2b9c9803c6a287cafa0a8c917211dddd23dcd2016f049690ee5219f5d3f1636e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 COMPASS_DB=/app/var/compass.sqlite3
WORKDIR /app
COPY apps/requirements.lock /app/apps/requirements.lock
RUN pip install --no-cache-dir -r apps/requirements.lock && useradd --uid 10001 --create-home compass && mkdir /app/var && chown compass:compass /app/var
COPY apps /app/apps
COPY data/synthetic/cases.json /app/data/synthetic/cases.json
USER compass
EXPOSE 8000
CMD ["python", "-m", "apps.compass", "serve", "--host", "0.0.0.0"]
