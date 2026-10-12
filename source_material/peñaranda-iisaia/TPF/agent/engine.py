"""Bucle del agente: el modelo pide reglas con herramientas hasta que puede
responder, y la respuesta final llega en streaming.

Cada vuelta usa `previous_response_id`, asi el proveedor mantiene la
conversacion (y su cache) del lado del servidor: solo se manda la salida de
las herramientas. Lo mismo permite encadenar preguntas de seguimiento en el
modo aclaracion.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterator

from wahapedia import store

from . import llm, prompts
from .tools import Toolbox, definitions

MAX_STEPS = 6  # vueltas con herramientas antes de forzar la respuesta


@dataclass
class ToolUse:
    """Una llamada a herramienta, para mostrar el progreso en la interfaz."""

    name: str
    title: str
    detail: str


@lru_cache(maxsize=1)
def instructions() -> str:
    codices = ", ".join(f"{c['name']} (`{c['id']}`)" for c in store.list_codices())
    return prompts.BASE.format(codices=codices or "ninguno", core_index=store.core_index_text())


def army(codex_id: str | None, detachment_id: str | None) -> str:
    """Descripcion del ejercito con sus ids, para que el modelo pueda pedir
    las reglas sin adivinar."""
    if not codex_id:
        return ""
    codex = next((c for c in store.list_codices() if c["id"] == codex_id), None)
    label = f"{codex['name'] if codex else codex_id} (codex `{codex_id}`)"
    detachment = next(
        (d for d in store.list_detachments(codex_id) or [] if d["id"] == detachment_id), None
    )
    if detachment:
        label += f", destacamento {detachment['name']} (`{detachment_id}`)"
    return label


@dataclass
class Turn:
    """Una consulta al agente. Se consume con `events()`; al terminar quedan
    `response_id` (para encadenar la siguiente), las reglas consultadas y
    `calls`: una entrada por llamada al modelo, con tokens y metadata."""

    input: str
    previous_response_id: str | None = None
    toolbox: Toolbox = field(default_factory=Toolbox)
    response_id: str | None = None
    calls: list[dict] = field(default_factory=list)

    @property
    def consulted(self) -> list[dict]:
        return self.toolbox.consulted

    def events(self) -> Iterator[str | ToolUse]:
        """Texto de la respuesta (str) intercalado con las llamadas a
        herramientas (ToolUse) en el orden en que ocurren."""
        tools = definitions()
        pending: str | list[dict] = self.input
        previous = self.previous_response_id

        for step in range(MAX_STEPS + 1):
            # en la ultima vuelta se fuerza la respuesta sin herramientas
            choice = "none" if step == MAX_STEPS else "auto"
            response = None
            started = time.monotonic()
            for kind, payload in llm.stream(instructions(), pending, tools, previous, choice):
                if kind == "delta":
                    yield payload
                else:
                    response = payload

            calls = [item for item in response["output"] if item.get("type") == "function_call"]
            self.calls.append(call_record(
                response, step=step, previous=previous, tool_choice=choice,
                tool_calls=len(calls), latency=time.monotonic() - started,
            ))
            previous = self.response_id = response["id"]
            if not calls:
                return

            pending = []
            for call in calls:
                try:
                    args = json.loads(call.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self.toolbox.call(call["name"], args)
                yield ToolUse(call["name"], *describe(call["name"], args, result))
                pending.append({
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": json.dumps(result, ensure_ascii=False),
                })

    def run(self) -> str:
        return "".join(e for e in self.events() if isinstance(e, str))


def call_record(response: dict, *, step: int, previous: str | None, tool_choice: str,
                tool_calls: int, latency: float) -> dict:
    """Uso y metadata de una llamada al modelo, tal como los reporta la API."""
    usage = response.get("usage") or {}
    return {
        "step": step,
        "model": response.get("model"),
        "reasoning_effort": (response.get("reasoning") or {}).get("effort"),
        "tool_choice": tool_choice,
        "tool_calls": tool_calls,
        "response_id": response.get("id"),
        "previous_response_id": previous,
        "input_tokens": usage.get("input_tokens"),
        "cached_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
        "latency_ms": round(latency * 1000),
    }


def describe(name: str, args: dict, result: dict) -> tuple[str, str]:
    """(titulo, detalle) de lo que hizo una herramienta, para la interfaz."""
    if name == "get_rules":
        rules = result.get("rules", [])
        names = [
            f"{r['name']} {r['number']}" if r.get("number") else r["name"]
            for r in rules if "error" not in r
        ]
        missing = [r["href"] for r in rules if "error" in r]
        detail = ", ".join(names)
        if missing:
            detail += f" · no existen: {', '.join(missing)}"
        plural = "regla" if len(names) == 1 else "reglas"
        return f"Leyó {len(names)} {plural}", detail
    if name == "get_codex_index":
        return "Abrió un índice de codex", f"`{args.get('codex_id')}`"
    if name == "search_rules":
        hits = [r["name"] for r in result.get("results", [])]
        return f"Buscó “{args.get('query')}”", ", ".join(hits) or "sin resultados"
    return name, ""


def clarify(question: str, previous_response_id: str | None = None, army_text: str = "") -> Turn:
    """`army_text`: el ejercito del jugador, de `army()` o de su lista."""
    text = prompts.CLARIFY.format(
        army=f"\nEJERCITO DEL JUGADOR:\n{army_text}\n" if army_text else "",
        question=question.strip(),
    )
    return Turn(input=text, previous_response_id=previous_response_id)


def arbitrate(
    situation: str,
    player_one: str,
    player_two: str,
    armies: tuple[str, str] = ("", ""),
) -> Turn:
    """`armies`: el ejercito de cada jugador como texto (vacio si no se indico)."""
    blocks = [
        f"\nEJERCITO DEL JUGADOR {n}:\n{text}\n"
        for n, text in enumerate(armies, start=1) if text
    ]
    text = prompts.ARBITRATE.format(
        situation=situation.strip() or "(no la describieron)",
        armies="".join(blocks),
        player_one=player_one.strip(),
        player_two=player_two.strip(),
    )
    return Turn(input=text)


__all__ = ["ToolUse", "Turn", "arbitrate", "army", "clarify"]
