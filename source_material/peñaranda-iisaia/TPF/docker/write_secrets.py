"""Genera .streamlit/secrets.toml (config de Auth0) a partir del entorno.

En un despliegue los secretos llegan como variables de entorno, pero
`st.login` los lee de secrets.toml. Este script lo escribe al arrancar:

    AUTH0_DOMAIN         dev-xxxx.us.auth0.com
    AUTH0_CLIENT_ID
    AUTH0_CLIENT_SECRET
    PUBLIC_URL           https://reglas.midominio.com (sin barra final)
    AUTH_COOKIE_SECRET   opcional: si falta, se genera uno y se guarda en
                         DATA_DIR para que las sesiones sobrevivan reinicios

Si ya hay un secrets.toml (montado a mano), no lo toca. Si faltan variables,
no escribe nada y la app muestra que falta configurar Auth0.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

import toml

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / ".streamlit" / "secrets.toml"
REQUIRED = ("AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET", "PUBLIC_URL")


def cookie_secret() -> str:
    if os.getenv("AUTH_COOKIE_SECRET"):
        return os.environ["AUTH_COOKIE_SECRET"]
    path = Path(os.getenv("DATA_DIR", ROOT / "data")) / "cookie_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        os.chmod(path, 0o600)
    return path.read_text(encoding="utf-8").strip()


def main() -> int:
    if TARGET.exists():
        print(f"secrets.toml ya existe, se usa tal cual: {TARGET}")
        return 0
    missing = [name for name in REQUIRED if not os.getenv(name)]
    if missing:
        print(f"Auth0 sin configurar (faltan {', '.join(missing)}): la app lo va a avisar.")
        return 0

    domain = os.environ["AUTH0_DOMAIN"].removeprefix("https://").strip("/")
    config = {
        "auth": {
            "redirect_uri": os.environ["PUBLIC_URL"].rstrip("/") + "/oauth2callback",
            "cookie_secret": cookie_secret(),
            "client_id": os.environ["AUTH0_CLIENT_ID"],
            "client_secret": os.environ["AUTH0_CLIENT_SECRET"],
            "server_metadata_url": f"https://{domain}/.well-known/openid-configuration",
        }
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(toml.dumps(config), encoding="utf-8")
    os.chmod(TARGET, 0o600)
    print(f"secrets.toml generado (redirect_uri = {config['auth']['redirect_uri']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
