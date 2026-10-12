"""Listas de ejercito exportadas de New Recruit (.rosz).

Un .rosz es un ZIP con un unico .ros: el XML de roster de BattleScribe. De
ahi se saca lo que el agente necesita para contestar sobre *tu* ejercito:

- faccion (catalogo) -> codex del almacen ("Imperium - Adeptus Astartes -
  Imperial Fists" -> space-marines);
- destacamentos (en 11a pueden ser varios, por Detachment Points);
- unidades: modelos, equipo, puntos, warlord, mejoras y su datasheet.

El texto de las reglas no sale del archivo: el agente lo lee del almacen,
asi que la lista solo aporta nombres y el vinculo con cada datasheet.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field

from defusedxml import ElementTree as SafeET

from wahapedia import store

MAX_FILE_BYTES = 1_000_000      # .rosz comprimido
MAX_XML_BYTES = 5_000_000       # .ros descomprimido (frena zip bombs)
GAME_SYSTEM = "Warhammer 40,000 11th Edition"

# catalogo de New Recruit (o una parte) -> id de codex en el almacen
CATALOGUES = {
    "adeptus astartes": "space-marines",
    "space marines": "space-marines",
    "orks": "orks",
}
CONFIGURATION = {"Battle Size", "Detachment", "Force Disposition", "Show/Hide Options"}


class ListError(ValueError):
    """La lista no se puede cargar; el mensaje es para el usuario."""


@dataclass
class Unit:
    name: str
    models: int
    points: int
    composition: list[str] = field(default_factory=list)  # "1x Intercessor Sergeant"
    wargear: list[str] = field(default_factory=list)      # "4x Bolt pistol"
    enhancements: list[str] = field(default_factory=list)
    warlord: bool = False
    datasheet_href: str | None = None


@dataclass
class ArmyList:
    name: str
    catalogue: str
    codex_id: str | None
    faction: str                 # nombre del codex, o el catalogo si no hay codex
    subfaction: str | None       # capitulo u otra subfaccion del catalogo
    detachments: list[dict]      # {"name", "id"}; id None si no esta en el almacen
    battle_size: str | None
    force_disposition: str | None
    points: int
    points_limit: int | None
    units: list[Unit]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ArmyList":
        return cls(**{**data, "units": [Unit(**u) for u in data["units"]]})


# --------------------------------------------------------------------------- #
# lectura del archivo
# --------------------------------------------------------------------------- #

def _tag(element) -> str:
    return element.tag.split("}")[-1]


def _children(element, name: str) -> list:
    """Hijos `name` dentro del contenedor plural (selections/selection...)."""
    return [c for box in element if _tag(box) == name + "s" for c in box if _tag(c) == name]


def _points(element) -> int:
    for cost in _children(element, "cost"):
        if cost.get("name") == "pts":
            return round(float(cost.get("value") or 0))
    return 0


def read_xml(data: bytes) -> bytes:
    """El .ros de dentro del .rosz, con los controles de tamano."""
    if len(data) > MAX_FILE_BYTES:
        raise ListError("El archivo es demasiado grande para ser una lista (máximo 1 MB).")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ListError("No es un .rosz válido: exportá la lista desde New Recruit como .rosz.")
    rosters = [i for i in archive.infolist() if i.filename.lower().endswith(".ros")]
    if len(rosters) != 1:
        raise ListError("El .rosz tiene que contener exactamente una lista (.ros).")
    if rosters[0].file_size > MAX_XML_BYTES:
        raise ListError("La lista descomprimida es demasiado grande.")
    with archive.open(rosters[0]) as handle:
        xml = handle.read(MAX_XML_BYTES + 1)
    if len(xml) > MAX_XML_BYTES:
        raise ListError("La lista descomprimida es demasiado grande.")
    return xml


def parse(data: bytes) -> ArmyList:
    """Lee un .rosz y devuelve la lista. Lanza ListError si no sirve."""
    try:
        root = SafeET.fromstring(read_xml(data))
    except SafeET.ParseError:
        raise ListError("El archivo no tiene un XML de lista válido.")
    except Exception as error:  # entidades, DTD y otros ataques que bloquea defusedxml
        if isinstance(error, ListError):
            raise
        raise ListError("El archivo tiene contenido no permitido.")

    if _tag(root) != "roster":
        raise ListError("El archivo no es una lista de BattleScribe / New Recruit.")
    system = root.get("gameSystemName", "")
    if system != GAME_SYSTEM:
        raise ListError(
            f"La lista es de «{system or 'un sistema desconocido'}»: por ahora solo se "
            f"aceptan listas de {GAME_SYSTEM}."
        )
    forces = _children(root, "force")
    if not forces:
        raise ListError("La lista no tiene ningún ejército cargado.")
    force = forces[0]

    catalogue = force.get("catalogueName", "")
    codex_id = codex_for(catalogue)
    codex_name = next((c["name"] for c in store.list_codices() if c["id"] == codex_id), None)
    parts = [p.strip() for p in catalogue.split(" - ")]
    subfaction = parts[-1] if len(parts) > 2 else None

    config = {s.get("name"): s for s in _children(force, "selection") if s.get("name") in CONFIGURATION}
    detachment_names = [s.get("name") for s in _children(config["Detachment"], "selection")] if "Detachment" in config else []
    detachments = [{"name": n, "id": detachment_id(codex_id, n)} for n in detachment_names]
    enhancement_names = enhancements_of(codex_id, [d["id"] for d in detachments if d["id"]])

    units = [
        unit_of(s, codex_id, enhancement_names)
        for s in _children(force, "selection")
        if s.get("name") not in CONFIGURATION and s.get("type") in ("unit", "model")
    ]
    limits = [c for c in _children(root, "costLimit") if c.get("name") == "pts"]
    return ArmyList(
        name=root.get("name") or "Lista sin nombre",
        catalogue=catalogue,
        codex_id=codex_id,
        faction=codex_name or (parts[1] if len(parts) > 1 else catalogue),
        subfaction=subfaction,
        detachments=detachments,
        battle_size=_first_child_name(config.get("Battle Size")),
        force_disposition=_first_child_name(config.get("Force Disposition")),
        points=_points(root),
        points_limit=round(float(limits[0].get("value"))) if limits else None,
        units=units,
    )


def _first_child_name(selection) -> str | None:
    if selection is None:
        return None
    children = _children(selection, "selection")
    return children[0].get("name") if children else None


# --------------------------------------------------------------------------- #
# vinculo con el almacen de reglas
# --------------------------------------------------------------------------- #

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower().replace("’", "'")).strip()


def codex_for(catalogue: str) -> str | None:
    lowered = catalogue.lower()
    for key, codex_id in CATALOGUES.items():
        if key in lowered:
            return codex_id
    return None


def detachment_id(codex_id: str | None, name: str) -> str | None:
    for det in store.list_detachments(codex_id) or [] if codex_id else []:
        if _norm(det["name"]) == _norm(name):
            return det["id"]
    return None


def enhancements_of(codex_id: str | None, detachment_ids: list[str]) -> set[str]:
    names: set[str] = set()
    for det in detachment_ids:
        for rule in store.list_detachment_rules(codex_id, det) or []:
            if rule["kind"] == "enhancement":
                names.add(_norm(rule["name"]))
    return names


def datasheet_href(codex_id: str | None, name: str) -> str | None:
    if not codex_id:
        return None
    for rule in store.list_codex_rules(codex_id, kind="datasheet") or []:
        if _norm(rule["name"]) == _norm(name):
            return rule["href"]
    return None


def unit_of(selection, codex_id: str | None, enhancement_names: set[str]) -> Unit:
    """Una unidad del roster. Las selecciones de tipo `model` cuentan modelos;
    las `upgrade` sin hijos son equipo (o warlord, o una mejora)."""
    name = selection.get("name")
    composition: Counter = Counter()
    wargear: Counter = Counter()
    enhancements: list[str] = []
    warlord = False

    def walk(node) -> None:
        nonlocal warlord
        for child in _children(node, "selection"):
            count = int(child.get("number") or 1)
            child_name = child.get("name")
            if child.get("type") == "model":
                composition[child_name] += count
                walk(child)
            elif _children(child, "selection"):
                walk(child)  # contenedor de opciones: interesa lo de adentro
            elif child_name == "Warlord":
                warlord = True
            elif _norm(child_name) in enhancement_names or "enhancement" in (child.get("group") or "").lower():
                enhancements.append(child_name)
            else:
                wargear[child_name] += count

    walk(selection)
    own = int(selection.get("number") or 1)
    if selection.get("type") == "model" and not composition:
        composition[name] += own
    return Unit(
        name=name,
        models=sum(composition.values()),
        points=_points(selection),
        composition=[f"{n}x {m}" for m, n in composition.items()],
        wargear=[f"{n}x {w}" for w, n in wargear.items()],
        enhancements=enhancements,
        warlord=warlord,
        datasheet_href=datasheet_href(codex_id, name),
    )


# --------------------------------------------------------------------------- #
# texto para el agente
# --------------------------------------------------------------------------- #

def describe(army: ArmyList) -> str:
    """La lista en texto compacto, con los ids y hrefs que el agente necesita
    para pedir las reglas sin adivinar."""
    faction = army.faction + (f" ({army.subfaction})" if army.subfaction else "")
    codex = f" (codex `{army.codex_id}`)" if army.codex_id else " (sin reglas de codex cargadas)"
    limit = f"/{army.points_limit}" if army.points_limit else ""
    lines = [f"Lista «{army.name}» de New Recruit: {faction}{codex}, {army.points}{limit} pts."]
    if army.detachments:
        dets = ", ".join(f"{d['name']} (`{d['id']}`)" if d["id"] else d["name"] for d in army.detachments)
        lines.append(f"Destacamentos: {dets}.")
    if army.force_disposition:
        lines.append(f"Force Disposition: {army.force_disposition}.")
    lines.append("Unidades:")
    for unit in army.units:
        tags = []
        if unit.warlord:
            tags.append("WARLORD")
        if unit.enhancements:
            tags.append("mejora: " + ", ".join(unit.enhancements))
        head = f"- {unit.name}" + (f" [{'; '.join(tags)}]" if tags else "")
        head += f" — {unit.models} modelos, {unit.points} pts"
        if unit.datasheet_href:
            head += f" — datasheet {unit.datasheet_href}"
        lines.append(head)
        if len(unit.composition) > 1:
            lines.append("  composición: " + ", ".join(unit.composition))
        if unit.wargear:
            lines.append("  equipo: " + ", ".join(unit.wargear))
    return "\n".join(lines)
