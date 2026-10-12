# Rules Companion 40k: app de jugadores (/) + panel de admin (/admin) detras
# de Caddy, en un solo puerto ($PORT, 8080 por defecto).
#
# Persistencia en el volumen /data: base de usuarios, credenciales de admin,
# secreto de la cookie (y las reglas, si no vinieron en la imagen).
# Configuracion por variables de entorno: ver DEPLOY.md.

FROM caddy:2-alpine AS caddy

FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    PORT=8080

COPY --from=caddy /usr/bin/caddy /usr/bin/caddy

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# las reglas descargadas (data/wahapedia) entran si estan en la carpeta al
# construir; .dockerignore deja afuera la cache de HTML, la base y secretos
COPY . .
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data /app/.streamlit \
    && chown -R app:app /app /data \
    && chmod +x docker/entrypoint.sh

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"

# arranca como root solo para preparar el volumen; el entrypoint baja a `app`
ENTRYPOINT ["/app/docker/entrypoint.sh"]
