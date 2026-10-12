#!/usr/bin/env bash
# Arranque del contenedor: prepara el volumen y los secretos, y levanta las
# dos apps de Streamlit (internas) detras de Caddy (puerto publico $PORT).
# Si cualquiera de los tres procesos muere, el contenedor termina y la
# plataforma lo reinicia.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export DATA_DIR="${DATA_DIR:-/data}"
export PORT="${PORT:-8080}"
# puertos internos de las dos apps (solo los ve Caddy)
export APP_PORT="${APP_PORT:-8501}" ADMIN_PORT="${ADMIN_PORT:-8502}"

# El volumen se monta como root: se le da al usuario `app` y se sigue sin
# privilegios.
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R app:app "$DATA_DIR" "$APP_DIR/.streamlit"
    export HOME=/home/app
    exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

cd "$APP_DIR"
export APP_DB_PATH="${APP_DB_PATH:-$DATA_DIR/app.db}"
export ADMIN_CREDENTIALS_PATH="${ADMIN_CREDENTIALS_PATH:-$DATA_DIR/admin_credentials.json}"

# Reglas: las que vinieron en la imagen; si no vinieron, se bajan una vez
# al volumen (tarda ~30 min la primera vez; despues quedan guardadas).
if [ -z "${RULES_DIR:-}" ]; then
    if [ -f "$APP_DIR/data/wahapedia/core.json" ]; then
        export RULES_DIR="$APP_DIR/data/wahapedia"
    else
        export RULES_DIR="$DATA_DIR/wahapedia"
    fi
fi
if [ ! -f "$RULES_DIR/core.json" ]; then
    echo "No hay reglas en $RULES_DIR: descargando de Wahapedia (~30 min la primera vez)..."
    python -m wahapedia sync
fi

python docker/write_secrets.py
python -c "import userdb; userdb.init()"

STREAMLIT=(python -m streamlit run --server.address 127.0.0.1 --server.headless true
           --browser.gatherUsageStats false)
"${STREAMLIT[@]}" app.py --server.port "$APP_PORT" &
"${STREAMLIT[@]}" admin.py --server.port "$ADMIN_PORT" --server.baseUrlPath admin &
caddy run --config docker/Caddyfile --adapter caddyfile &

echo "Listo: app en / y panel de admin en /admin (puerto $PORT)"
wait -n
exit $?
