"""Herramientas que el modelo puede llamar, sobre el almacen de wahapedia/.

Son tres, a proposito pocas:

- get_rules: texto completo de una o varias reglas por href. Es la principal:
  el indice de core vive en el contexto y el codex se carga con la siguiente.
- get_codex_index: indice de un codex (army rules, destacamentos, datasheets).
- search_rules: respaldo por si una regla no se ubica por el indice (una
  keyword o una datasheet con otro nombre). Busqueda lexica simple.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from wahapedia import store

MAX_SEARCH_RESULTS = 8


def codex_ids() -> list[str]:
    return [c["id"] for c in store.list_codices()]


def definitions() -> list[dict]:
    """Esquemas de las herramientas en el formato de la Responses API."""
    return [
        {
            "type": "function",
            "name": "get_rules",
            "description": (
                "Full text of one or more rules, by href (from the indexes or from "
                "the `references` of a rule already read). Ask for every rule you "
                "need in a single call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hrefs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "e.g. /core/rules/2-charge-step, "
                        "/codices/orks/rules/boyz, "
                        "/codices/space-marines/detachments/gladius-task-force/rules/armour-of-contempt",
                    }
                },
                "required": ["hrefs"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_codex_index",
            "description": (
                "Index of a faction codex: army rules, detachments (with their "
                "detachment rule, enhancements and stratagems) and datasheets."
            ),
            "parameters": {
                "type": "object",
                "properties": {"codex_id": {"type": "string", "enum": codex_ids()}},
                "required": ["codex_id"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "search_rules",
            "description": (
                "Fallback keyword search over rule names and text (English terms). "
                "Use it only when the indexes do not show where a rule is."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


@dataclass
class Toolbox:
    """Ejecuta las llamadas del modelo y recuerda que reglas leyo, para
    mostrarlas como fuentes en la interfaz."""

    consulted: list[dict] = field(default_factory=list)

    def call(self, name: str, args: dict) -> dict:
        if name == "get_rules":
            return {"rules": [self._rule(href) for href in args.get("hrefs", [])]}
        if name == "get_codex_index":
            text = store.codex_index_text(args.get("codex_id", ""))
            return {"index": text} if text else {"error": f"unknown codex: {args.get('codex_id')}"}
        if name == "search_rules":
            return {"results": search(args.get("query", ""))}
        return {"error": f"unknown tool: {name}"}

    def _rule(self, href: str) -> dict:
        rule = store.get_by_href(href) or _guess(href)
        if rule is None:
            return {"href": href, "error": "not found"}
        if all(r["href"] != rule["href"] for r in self.consulted):
            self.consulted.append(rule)
        return {
            "href": rule["href"],
            "layer": rule["layer"],
            "kind": rule["kind"],
            "name": rule["name"],
            "number": rule.get("number"),
            "section": rule["section"],
            "source_url": rule["source_url"],
            "text": rule["text"],
            "figures": [
                {"caption": f["caption"], "description": f["description"]}
                for f in rule.get("figures", []) if f["description"]
            ],
            "references": [{"name": r["name"], "href": r["href"]} for r in rule["references"]],
        }


def _guess(href: str) -> dict | None:
    """Rescata un href mal armado de core rules: el modelo a veces arma el id
    con el numero del reglamento ('/core/rules/11.02-charge-step') o con el
    nombre en vez del id del indice."""
    match = re.fullmatch(r"/?core/rules/(.+)", href.strip())
    if match is None:
        return None
    wanted = match.group(1).lower().strip("/").split("/")[-1]  # ".../core-stratagems/fire-overwatch"
    rules = store.all_rules()
    number = re.match(r"\d+(\.\d+)+", wanted)
    if number:
        found = next((r for r in rules if r["layer"] == "core" and r.get("number") == number.group(0)), None)
        if found:
            return found
    name = re.sub(r"[^a-z0-9]+", "-", re.sub(r"^[\d.\-]+", "", wanted)).strip("-")
    return next(
        (r for r in rules if r["layer"] == "core"
         and re.sub(r"[^a-z0-9]+", "-", r["name"].lower()).strip("-").lstrip("0123456789-") == name),
        None,
    )


def search(query: str) -> list[dict]:
    terms = [t for t in re.findall(r"[a-z0-9']+", query.lower()) if len(t) > 2]
    if not terms:
        return []
    scored = []
    for rule in store.all_rules():
        name, text = rule["name"].lower(), rule["text"].lower()
        score = sum(3 * (t in name) + (t in text) for t in terms)
        if query.lower() in name:
            score += 10
        if score:
            scored.append((score, rule))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        store.summary(rule) | {"codex_id": rule.get("codex_id")}
        for _, rule in scored[:MAX_SEARCH_RESULTS]
    ]
