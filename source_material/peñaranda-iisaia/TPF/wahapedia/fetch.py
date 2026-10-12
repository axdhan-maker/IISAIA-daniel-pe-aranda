"""Descarga de paginas de Wahapedia con cache en disco.

El HTML crudo se guarda en data/wahapedia/raw/ para no volver a pedir una
pagina que ya se bajo (las datasheets son cientos de requests). Entre
requests reales se espera DELAY segundos para no castigar el sitio.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.getenv("RULES_DIR") or ROOT / "data" / "wahapedia") / "raw"

BASE_URL = "https://wahapedia.ru"
EDITION = "wh40k11ed"
DELAY = 1.5
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (rules-companion-40k; proyecto academico)"}

_last_request = 0.0


def url_for(path: str) -> str:
    """Path relativo a la edicion ('the-rules/core-rules/') -> URL absoluta."""
    return urljoin(f"{BASE_URL}/{EDITION}/", path)


def _cache_path(url: str) -> Path:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", url.removeprefix(BASE_URL).strip("/"))
    return CACHE_DIR / f"{name}.html"


def get(url: str, refresh: bool = False) -> str:
    """HTML de la pagina; usa la cache salvo que se pida refresh."""
    global _last_request
    path = _cache_path(url)
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")

    wait = DELAY - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    _last_request = time.monotonic()
    response.raise_for_status()
    response.encoding = "utf-8"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text, encoding="utf-8")
    return response.text
