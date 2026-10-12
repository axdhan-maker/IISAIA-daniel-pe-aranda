"""Almacen de reglas en JSON e indice para el agente.

Layout en data/wahapedia/:

    core.json                    core rules + rules appendix (capa core)
    codices/<codex>.json         army rules, destacamentos y datasheets
    index/core.json | core.md    indice de core (vive siempre en el contexto)
    index/<codex>.json | .md     indice de cada codex (se carga a pedido)
    raw/                         cache del HTML crudo (ver fetch.py)

Las funciones de consulta siguen las operaciones del openapi del TP2
(listCoreRules, getCoreRule, listCodexRules, ...), para poder exponerlas
despues como herramientas del agente o como endpoints sin cambiar el modelo.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from . import parse

ROOT = Path(__file__).resolve().parent.parent
# RULES_DIR permite mover el almacen (en Docker: a la imagen o al volumen)
DATA_DIR = Path(os.getenv("RULES_DIR") or ROOT / "data" / "wahapedia")
CORE_PATH = DATA_DIR / "core.json"
CODEX_DIR = DATA_DIR / "codices"
INDEX_DIR = DATA_DIR / "index"

SUMMARY_FIELDS = ("id", "layer", "kind", "name", "section", "href", "number")
KIND_LABELS = {
    "detachment_rule": "Detachment rule",
    "enhancement": "Enhancements",
    "stratagem": "Stratagems",
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# referencias
# --------------------------------------------------------------------------- #

def _keys(rule: dict) -> list[tuple[str, str]]:
    page = rule.get("_page")
    if page is None:
        key = parse.page_key(rule["source_url"], "")
        if key is None:
            return []
        page = key[0]
    return [(page, anchor) for anchor in rule["anchors"]]


def resolve_references(rules: list[dict], known: list[dict]) -> int:
    """Convierte los enlaces crudos de `rules` en `references`.

    `known` son las reglas ya guardadas de otras fuentes (para resolver, por
    ejemplo, enlaces de un codex al core sin re-scrapear el core). Devuelve
    cuantos enlaces no se pudieron resolver: apuntan a otra faccion o a un
    encabezado de grupo sin texto propio.
    """
    registry: dict[tuple[str, str], list[dict]] = {}
    for rule in [*rules, *known]:
        for key in _keys(rule):
            registry.setdefault(key, []).append(rule)

    unresolved = 0
    for rule in rules:
        refs, seen = [], {rule["href"]}
        for href in rule.pop("_links", []):
            key = parse.page_key(href, rule["_page"])
            candidates = registry.get(key) if key else None
            if not candidates:
                unresolved += 1
                continue
            # una misma ancla puede repetirse entre destacamentos: gana la
            # del destacamento de la regla que la menciona
            target = next(
                (c for c in candidates if c.get("detachment_id") == rule.get("detachment_id")),
                candidates[0],
            )
            if target["href"] in seen:
                continue
            seen.add(target["href"])
            refs.append({
                "layer": target["layer"],
                "rule_id": target["id"],
                "name": target["name"],
                "href": target["href"],
            })
        rule["references"] = refs
    return unresolved


# --------------------------------------------------------------------------- #
# guardado
# --------------------------------------------------------------------------- #

def _public(rule: dict) -> dict:
    return {k: v for k, v in rule.items() if not k.startswith("_")}


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def diff(old: list[dict], new: list[dict]) -> dict:
    """Cambios entre dos versiones de una fuente (campos del `Sync` del TP2)."""
    before = {r["href"]: r for r in old}
    after = {r["href"]: r for r in new}
    updated = sum(
        1 for href, rule in after.items()
        if href in before and (
            before[href]["text"] != rule["text"]
            or before[href]["references"] != rule["references"]
        )
    )
    return {
        "rules_added": len(after.keys() - before.keys()),
        "rules_updated": updated,
        "rules_removed": len(before.keys() - after.keys()),
    }


def save_core(rules: list[dict], scraped_at: str) -> dict:
    old = _read(CORE_PATH)
    rules = [_public(r) | {"scraped_at": scraped_at} for r in rules]
    _write(CORE_PATH, {
        "layer": "core",
        "source": {
            "id": "core",
            "name": "Warhammer 40,000 Core Rules (11th edition)",
            "source_url": parse.fetch.url_for(parse.CORE_PAGES["core-rules"][0]),
            "rule_count": len(rules),
            "last_synced_at": scraped_at,
        },
        "rules": rules,
    })
    write_index("core", rules)
    return diff(old["rules"] if old else [], rules)


def save_codex(source: dict, detachments: list[dict], rules: list[dict], scraped_at: str) -> dict:
    path = CODEX_DIR / f"{source['id']}.json"
    old = _read(path)
    rules = [_public(r) | {"scraped_at": scraped_at} for r in rules]
    source = source | {"rule_count": len(rules), "last_synced_at": scraped_at}
    _write(path, {"layer": "codex", "source": source, "detachments": detachments, "rules": rules})
    write_index(source["id"], rules, source=source, detachments=detachments)
    return diff(old["rules"] if old else [], rules)


def saved_rules(exclude: set[str]) -> list[dict]:
    """Reglas ya guardadas de las fuentes que no se estan sincronizando."""
    rules = []
    if "core" not in exclude and CORE_PATH.exists():
        rules += _read(CORE_PATH)["rules"]
    for path in sorted(CODEX_DIR.glob("*.json")):
        if path.stem not in exclude:
            rules += _read(path)["rules"]
    return rules


# --------------------------------------------------------------------------- #
# indice
# --------------------------------------------------------------------------- #

def summary(rule: dict) -> dict:
    return {k: rule[k] for k in SUMMARY_FIELDS if rule.get(k) is not None}


def _label(rule: dict) -> str:
    return f"{rule['number']} {rule['name']}" if rule.get("number") else rule["name"]


def render_tree(rules: list[dict]) -> list[str]:
    """Arbol del indice a partir de `section`: una linea por regla, con los
    encabezados de grupo que no son reglas intercalados donde corresponde."""
    lines: list[str] = []
    previous: list[str] = []
    for rule in rules:
        path = rule["section"]
        common = 0
        while common < min(len(previous), len(path) - 1) and previous[common] == path[common]:
            common += 1
        for depth in range(common, len(path) - 1):
            lines.append("  " * depth + f"- {path[depth]}")
        lines.append("  " * (len(path) - 1) + f"- {_label(rule)} `{rule['id']}`")
        previous = path
    return lines


def render_core_index(rules: list[dict]) -> str:
    return "\n".join([
        "# Core rules (Warhammer 40,000, 11th edition)",
        "Full rule: GET /core/rules/{id}. Ids in backticks.",
        "",
        *render_tree(rules),
    ])


def render_codex_index(source: dict, detachments: list[dict], rules: list[dict]) -> str:
    codex = source["id"]
    lines = [
        f"# {source['name']} (codex `{codex}`)",
        "",
        f"## Army rules — GET /codices/{codex}/rules/{{id}}",
    ]
    lines += [f"- {r['name']} `{r['id']}`" for r in rules if r["kind"] == "army_rule"]

    lines += ["", f"## Detachments — GET /codices/{codex}/detachments/{{detachment}}/rules/{{id}}"]
    for det in detachments:
        lines.append(f"### {det['name']} `{det['id']}`")
        own = [r for r in rules if r.get("detachment_id") == det["id"]]
        for kind, label in KIND_LABELS.items():
            items = [f"{r['name']} `{r['id']}`" for r in own if r["kind"] == kind]
            if items:
                lines.append(f"- {label}: " + "; ".join(items))

    datasheets = [f"{r['name']} `{r['id']}`" for r in rules if r["kind"] == "datasheet"]
    lines += ["", f"## Datasheets — GET /codices/{codex}/rules/{{id}}", "; ".join(datasheets)]
    return "\n".join(lines)


def write_index(name: str, rules: list[dict], source: dict | None = None,
                detachments: list[dict] | None = None) -> None:
    _write(INDEX_DIR / f"{name}.json", [summary(r) for r in rules])
    text = (render_core_index(rules) if source is None
            else render_codex_index(source, detachments or [], rules))
    (INDEX_DIR / f"{name}.md").write_text(text + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# consulta (mismas operaciones que el openapi del TP2)
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=None)
def _core() -> dict:
    data = _read(CORE_PATH)
    if data is None:
        raise FileNotFoundError(f"No existe {CORE_PATH}. Corre primero: python -m wahapedia sync")
    return data


@lru_cache(maxsize=None)
def _codex(codex_id: str) -> dict | None:
    return _read(CODEX_DIR / f"{codex_id}.json")


def list_core_rules() -> list[dict]:
    return [summary(r) for r in _core()["rules"]]


def get_core_rule(rule_id: str) -> dict | None:
    return next((r for r in _core()["rules"] if r["id"] == rule_id), None)


def list_codices() -> list[dict]:
    return [_read(p)["source"] for p in sorted(CODEX_DIR.glob("*.json"))]


def list_codex_rules(codex_id: str, kind: str | None = None) -> list[dict] | None:
    codex = _codex(codex_id)
    if codex is None:
        return None
    return [
        summary(r) for r in codex["rules"]
        if r["detachment_id"] is None and (kind is None or r["kind"] == kind)
    ]


def get_codex_rule(codex_id: str, rule_id: str) -> dict | None:
    codex = _codex(codex_id) or {"rules": []}
    return next(
        (r for r in codex["rules"] if r["detachment_id"] is None and r["id"] == rule_id), None
    )


def list_detachments(codex_id: str) -> list[dict] | None:
    codex = _codex(codex_id)
    return None if codex is None else codex["detachments"]


def list_detachment_rules(codex_id: str, detachment_id: str) -> list[dict] | None:
    codex = _codex(codex_id)
    if codex is None or not any(d["id"] == detachment_id for d in codex["detachments"]):
        return None
    return [summary(r) for r in codex["rules"] if r["detachment_id"] == detachment_id]


def get_detachment_rule(codex_id: str, detachment_id: str, rule_id: str) -> dict | None:
    codex = _codex(codex_id) or {"rules": []}
    return next(
        (r for r in codex["rules"]
         if r["detachment_id"] == detachment_id and r["id"] == rule_id),
        None,
    )


def all_rules() -> list[dict]:
    """Todas las reglas guardadas, de todas las capas (para busquedas)."""
    rules = list(_core()["rules"])
    for path in sorted(CODEX_DIR.glob("*.json")):
        rules += _codex(path.stem)["rules"]
    return rules


def get_by_href(href: str) -> dict | None:
    """Regla completa a partir de su `href` (el que traen las references)."""
    parts = [p for p in href.split("/") if p]
    match parts:
        case ["core", "rules", rule_id]:
            return get_core_rule(rule_id)
        case ["codices", codex_id, "rules", rule_id]:
            return get_codex_rule(codex_id, rule_id)
        case ["codices", codex_id, "detachments", detachment_id, "rules", rule_id]:
            return get_detachment_rule(codex_id, detachment_id, rule_id)
    return None


def core_index_text() -> str:
    return (INDEX_DIR / "core.md").read_text(encoding="utf-8")


def codex_index_text(codex_id: str) -> str | None:
    path = INDEX_DIR / f"{codex_id}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None
