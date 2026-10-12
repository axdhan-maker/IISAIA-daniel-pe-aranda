"""Cliente minimo para el endpoint /openai/v1/responses de Azure AI Foundry,
con herramientas (function calling) y streaming."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

import requests
from dotenv import load_dotenv

import env

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DEFAULT_MODEL = "gpt-5.6-luna"
# el endpoint acepta: none, minimal, low, medium, high, xhigh, max
DEFAULT_EFFORT = "medium"
TIMEOUT = 300
RETRIES = 2


class LLMError(RuntimeError):
    pass


def _config() -> tuple[str, str, str]:
    url = env.get("azure_foundry_url").strip()
    key = env.get("azure_foundry_api_key").strip()
    model = env.get("azure_foundry_model", DEFAULT_MODEL).strip()
    if not url or not key:
        raise LLMError(
            "Faltan azure_foundry_url / azure_foundry_api_key en el archivo .env"
        )
    return url, key, model


def _post(url: str, key: str, payload: dict) -> requests.Response:
    """POST con reintentos ante fallas de red (DNS o conexion), que en una
    consulta de varias vueltas se notan mas."""
    for attempt in range(RETRIES + 1):
        try:
            return requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=TIMEOUT,
                stream=True,
            )
        except requests.ConnectionError as error:
            if attempt == RETRIES:
                raise LLMError(f"No se pudo conectar con Azure: {error}") from error
            time.sleep(1 + attempt)
    raise AssertionError("inalcanzable")


def stream(
    instructions: str,
    input: str | list[dict],
    tools: list[dict] | None = None,
    previous_response_id: str | None = None,
    tool_choice: str = "auto",
) -> Iterator[tuple[str, object]]:
    """Una vuelta del modelo, consumida por SSE.

    Genera ("delta", texto) a medida que llega la respuesta y termina con
    ("completed", respuesta), donde respuesta es el objeto completo con sus
    `output` (mensajes y llamadas a herramientas) y su `id`, que sirve de
    `previous_response_id` para la vuelta siguiente.
    """
    url, key, model = _config()
    # este deployment no acepta temperature; se deja el default del modelo
    payload = {
        "model": model,
        "instructions": instructions,
        "input": input,
        "reasoning": {"effort": env.get("azure_foundry_reasoning_effort", DEFAULT_EFFORT).strip()},
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id

    with _post(url, key, payload) as response:
        if response.status_code >= 400:
            raise LLMError(f"Azure respondio {response.status_code}: {response.text[:300]}")
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                break
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "response.output_text.delta":
                yield "delta", event.get("delta", "")
            elif kind == "response.completed":
                yield "completed", event["response"]
                return
            elif kind in ("error", "response.failed"):
                raise LLMError(str(event.get("message") or event.get("response", event)))
    raise LLMError("La respuesta del modelo se corto antes de terminar")
