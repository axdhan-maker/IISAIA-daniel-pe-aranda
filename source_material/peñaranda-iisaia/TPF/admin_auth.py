"""Credenciales del panel de admin.

Orden de prioridad:

1. Las definidas desde el panel, guardadas en ADMIN_CREDENTIALS_PATH
   (por defecto data/admin_credentials.json; en Docker, el volumen /data).
2. Las del entorno: admin_user y admin_password_hash.
3. Las de fabrica: 4dmin / pa$$temporal.

Las de 2 y 3 son temporales: al ingresar con ellas, el panel exige definir
credenciales propias, que pasan a ser las de 1. Asi cualquier despliegue nuevo
arranca con una clave conocida y la cambia en el primer ingreso.

Las contrasenas nunca se guardan en texto plano: van hasheadas con
PBKDF2-SHA256. Para generar un hash a mano (variable admin_password_hash):

    python admin_auth.py "contrasena"
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import env

ROOT = Path(__file__).resolve().parent
ITERATIONS = 600_000
MIN_LENGTH = 10

DEFAULT_USER = "4dmin"
# hash de la contrasena de fabrica ("pa$$temporal")
DEFAULT_HASH = (
    "pbkdf2_sha256$600000$5f0c8d1e9a2b47c3b6e1d0f9a8c7b6a5$"
    "66e610950d660d6a4d63cafa2429b110f6a4b55665e716c7b7b89258ebe3a761"
)

# bloqueo global (compartido por todas las sesiones del proceso): tras
# MAX_FAILURES intentos fallidos en WINDOW segundos, nadie entra por LOCKOUT
MAX_FAILURES = 5
WINDOW = 15 * 60
LOCKOUT = 15 * 60
_failures: list[float] = []
_locked_until = 0.0
_lock = threading.Lock()


@dataclass
class Credentials:
    user: str
    password_hash: str
    temporary: bool  # True: hay que reemplazarlas en el primer ingreso


def credentials_path() -> Path:
    return Path(os.getenv("ADMIN_CREDENTIALS_PATH") or ROOT / "data" / "admin_credentials.json")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def _matches(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
    except ValueError:
        return False
    return hmac.compare_digest(candidate, digest)


def current() -> Credentials:
    path = credentials_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return Credentials(data["user"], data["password_hash"], temporary=False)
    if env.get("admin_user") and env.get("admin_password_hash"):
        return Credentials(env.get("admin_user"), env.get("admin_password_hash"), temporary=True)
    return Credentials(DEFAULT_USER, DEFAULT_HASH, temporary=True)


def locked_for() -> float:
    """Segundos que faltan para que se levante el bloqueo (0 si no hay)."""
    return max(0.0, _locked_until - time.monotonic())


def verify(user: str, password: str) -> Credentials | None:
    """Las credenciales vigentes si coinciden, None si no (o si hay bloqueo).
    Usuario y contrasena se comparan siempre los dos, en tiempo constante."""
    global _locked_until
    if locked_for():
        return None
    creds = current()
    user_ok = hmac.compare_digest(user.encode(), creds.user.encode())
    password_ok = _matches(password, creds.password_hash)
    if user_ok and password_ok:
        return creds
    with _lock:
        now = time.monotonic()
        _failures[:] = [t for t in _failures if now - t < WINDOW] + [now]
        if len(_failures) >= MAX_FAILURES:
            _locked_until = now + LOCKOUT
            _failures.clear()
    return None


def problems(user: str, password: str, repeated: str) -> list[str]:
    """Motivos por los que no se aceptan unas credenciales nuevas."""
    found = []
    if len(user.strip()) < 3:
        found.append("El usuario debe tener al menos 3 caracteres.")
    if len(password) < MIN_LENGTH:
        found.append(f"La contraseña debe tener al menos {MIN_LENGTH} caracteres.")
    if password != repeated:
        found.append("Las contraseñas no coinciden.")
    if _matches(password, current().password_hash) or _matches(password, DEFAULT_HASH):
        found.append("La contraseña nueva tiene que ser distinta de la temporal.")
    return found


def save(user: str, password: str) -> None:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "user": user.strip(),
        "password_hash": hash_password(password),
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit('uso: python admin_auth.py "contrasena"')
    print(f"admin_password_hash={hash_password(sys.argv[1])}")
