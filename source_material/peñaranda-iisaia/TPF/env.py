"""Lectura de variables de entorno sin importar mayusculas.

En local se usan en minusculas (.env: azure_foundry_url); las plataformas de
despliegue suelen pedirlas en mayusculas (AZURE_FOUNDRY_URL). Se aceptan las
dos.
"""

from __future__ import annotations

import os


def get(name: str, default: str = "") -> str:
    return os.getenv(name) or os.getenv(name.upper()) or default
