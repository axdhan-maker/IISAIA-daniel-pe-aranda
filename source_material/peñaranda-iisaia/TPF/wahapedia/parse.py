"""Paginas de Wahapedia -> reglas con su lugar en el indice.

La jerarquia sale del recuadro "Contents" de cada pagina: sus niveles de
sangria (i10, i30, i50...) dicen que regla cuelga de cual. Las anclas que no
figuran en el indice (sub-reglas, estratagemas) cuelgan de la ultima entrada
del indice que las precede.

Cada regla sale como un dict con la forma de `Rule` del openapi del TP2, mas
`anchors`: las anclas de Wahapedia que resuelven a la regla (la propia y
las de encabezados de grupo sin texto que la preceden, como "Attached Units",
para que un enlace a ese encabezado caiga en su primera regla). Los campos
`_page` y `_links` son internos: store.py los usa para resolver las
referencias y no se guardan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from . import fetch
from .html2md import Converter, Segment, enhancement_name, soup_of, tidy, tooltip_links

CORE_PAGES = {
    # page_key: (path, prefijo de id, seccion raiz)
    "core-rules": ("the-rules/core-rules/", "", None),
    "rules-appendix": ("the-rules/rules-appendix/", "appendix-", "Rules Appendix"),
}
SKIP_SECTIONS = {"Books", "FAQ", "Keywords", "Boarding Actions"}
DATASHEET_SKIP = {"STRATAGEMS", "DETACHMENT ABILITY", "ENHANCEMENTS"}


def slug(text: str) -> str:
    text = text.lower().replace("’", "").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "x"


def page_key(href: str, current: str) -> tuple[str, str] | None:
    """href de un enlace -> (pagina, ancla), en el mismo formato que `_page`.

    Paginas: 'core-rules', 'rules-appendix', 'faction/<id>' y
    'datasheet/<faccion>/<Nombre>'. Devuelve None si apunta fuera de lo que
    se scrapea (otra edicion, un PDF, etc.).
    """
    if href.startswith("#"):
        return current, href[1:]
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc != "wahapedia.ru":
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 3 or parts[0] != fetch.EDITION:
        return None
    if parts[1] == "the-rules" and parts[2] in CORE_PAGES:
        return parts[2], parsed.fragment
    if parts[1] == "factions":
        if len(parts) == 3:
            return f"faction/{parts[2]}", parsed.fragment
        return f"datasheet/{parts[2]}/{parts[3]}", ""
    return None


# --------------------------------------------------------------------------- #
# indice y jerarquia
# --------------------------------------------------------------------------- #

def parse_toc(soup: BeautifulSoup) -> dict[str, int]:
    """Ancla -> nivel de sangria del recuadro Contents de la pagina.

    Los separadores de partes del core ("BASIC RULES") estan al mismo nivel
    que los capitulos; se los sube a nivel 0 para que los capitulos cuelguen
    de ellos.
    """
    toc: dict[str, int] = {}
    nav = soup.select_one("div.contentsWrap div.NavColumns3")
    if nav is None:
        return toc
    for entry in nav.find_all("div", recursive=False):
        link = entry.find("a", href=True)
        indent = next((c for c in entry.get("class", []) if re.fullmatch(r"i\d+", c)), None)
        if link is None or indent is None:
            continue
        level = int(indent[1:])
        label = link.get_text(" ", strip=True)
        if level == 10 and label.isupper() and not label[:1].isdigit():
            level = 0
        toc.setdefault(link["href"].lstrip("#"), level)
    return toc


@dataclass
class Placed:
    segment: Segment
    path: list[tuple[str, str]]  # (titulo, ancla) de la raiz a la regla

    @property
    def title(self) -> str:
        return self.path[-1][0]

    @property
    def section(self) -> list[str]:
        return [title for title, _ in self.path]


def place(segments: list[Segment], toc: dict[str, int]) -> list[Placed]:
    stack: list[tuple[int, str, str]] = []
    placed = []
    for seg in segments:
        title = seg.title or seg.anchor.replace("-", " ").strip()
        if seg.anchor in toc:
            level = toc[seg.anchor]
            while stack and stack[-1][0] >= level:
                stack.pop()
            path = [(t, a) for _, t, a in stack] + [(title, seg.anchor)]
            stack.append((level, title, seg.anchor))
        else:
            path = [(t, a) for _, t, a in stack] + [(title, seg.anchor)]
        placed.append(Placed(seg, path))
    return placed


def unique(rule_id: str, taken: set[str]) -> str:
    candidate, n = rule_id, 2
    while candidate in taken:
        candidate, n = f"{rule_id}-{n}", n + 1
    taken.add(candidate)
    return candidate


def base_rule(seg: Segment, *, rule_id, layer, kind, name, section, href, url, page) -> dict:
    return {
        "id": rule_id,
        "layer": layer,
        "kind": kind,
        "name": name,
        "section": section,
        "href": href,
        "text": seg.text,
        "references": [],
        "source_url": f"{url}#{seg.meta.get('target', seg.anchor)}",
        "_page": page,
        "anchors": [seg.anchor],
        "_links": seg.links,
    }


# --------------------------------------------------------------------------- #
# core rules
# --------------------------------------------------------------------------- #

def parse_core(html: str, key: str) -> list[dict]:
    path, prefix, root = CORE_PAGES[key]
    url = fetch.url_for(path)
    soup = soup_of(html)
    segments = Converter(tooltip_links(soup), figures=True).split(soup.body)

    rules, taken, pending = [], set(), []
    for item in place(segments, parse_toc(soup)):
        seg = item.segment
        if item.section[0] in SKIP_SECTIONS:
            continue
        if not seg.text:  # encabezado de grupo sin texto propio
            pending.append(seg.anchor)
            continue
        rule_id = unique(prefix + slug(seg.anchor), taken)
        section = ([root] if root else []) + item.section
        rule = base_rule(
            seg, rule_id=rule_id, layer="core", kind="core_rule", name=item.title,
            section=section, href=f"/core/rules/{rule_id}", url=url, page=key,
        )
        rule["anchors"] += pending
        pending = []
        rule["number"] = seg.number or None
        rule["figures"] = [
            {
                "id": f"{rule_id}-fig-{n}",
                "caption": fig["caption"],
                "description": fig["description"],
                # wahapedia = recuadro original bajo el diagrama; None = falta
                # generarla (pendiente: descripcion con un modelo de vision)
                "description_source": "wahapedia" if fig["description"] else None,
                "image_url": fetch.BASE_URL + fig["src"],
            }
            for n, fig in enumerate(seg.figures, start=1)
        ]
        rules.append(rule)
    return rules


# --------------------------------------------------------------------------- #
# codex (pagina de faccion)
# --------------------------------------------------------------------------- #

def mark_enhancements(soup: BeautifulSoup) -> None:
    """Las mejoras no tienen ancla propia: se inserta una antes de cada una
    para que el conversor las separe como reglas independientes."""
    for pts in soup.select("ul.EnhancementsPts"):
        table = pts.find_parent("table") or pts
        group = table.find_previous("a", attrs={"name": True, "data-kind": False})
        name, _ = enhancement_name(pts)
        anchor = soup.new_tag("a")
        anchor["name"] = f"enh-{slug(name or 'enhancement')}"
        anchor["data-kind"] = "enhancement"
        table.insert_before(anchor)
        anchor["data-target"] = group["name"] if group else ""


def datasheet_links(soup: BeautifulSoup, codex_id: str) -> list[str]:
    seen: dict[str, None] = {}
    prefix = f"/{fetch.EDITION}/factions/{codex_id}/"
    for link in soup.select(f'a[href^="{prefix}"]'):
        name = link["href"][len(prefix):]
        # las datasheets van en mayuscula; en minuscula son subpaginas de
        # capitulos (blood-angels, ultramarines...)
        if name[:1].isupper() and "#" not in name and "/" not in name:
            seen.setdefault(name, None)
    return list(seen)


def parse_codex(html: str, codex_id: str) -> tuple[dict, list[dict], list[dict], list[str]]:
    """Devuelve (fuente, destacamentos, reglas, nombres de datasheets)."""
    url = fetch.url_for(f"factions/{codex_id}/")
    soup = soup_of(html)
    mark_enhancements(soup)
    targets = {a["name"]: a["data-target"] for a in soup.select("a[data-kind]")}
    segments = Converter(tooltip_links(soup)).split(soup.body)
    for seg in segments:
        if seg.anchor in targets:  # citar la mejora apunta al bloque Enhancements
            seg.meta["target"] = targets[seg.anchor]

    title = soup.select_one("h1")
    source = {
        "id": codex_id,
        "name": tidy(title.get_text(" ")) if title else codex_id.replace("-", " ").title(),
        "source_url": url,
    }

    detachments: dict[str, dict] = {}
    rules, taken, pending = [], {}, []
    for item in place(segments, parse_toc(soup)):
        seg = item.segment
        top_title, top_anchor = item.path[0]
        if top_title in SKIP_SECTIONS:
            continue

        if top_title == "Army Rules":
            if len(item.path) == 1 or not seg.text:
                pending.append(seg.anchor)
                continue
            kind = seg.meta.get("kind") or "army_rule"
            section = item.section
            scope, href_base = "codex", f"/codices/{codex_id}/rules/"
            detachment_id = None
        else:
            detachment_id = slug(top_anchor)
            if len(item.path) == 1:
                detachments[detachment_id] = {
                    "id": detachment_id,
                    "codex_id": codex_id,
                    "name": top_title,
                    "description": seg.text or None,
                    "source_url": f"{url}#{top_anchor}",
                }
                pending.append(seg.anchor)
                continue
            if not seg.text:  # "Detachment Rules", "Stratagems": solo agrupan
                pending.append(seg.anchor)
                continue
            kind = seg.meta.get("kind") or "detachment_rule"
            group = {"stratagem": "Stratagems", "enhancement": "Enhancements"}.get(kind)
            section = [top_title, group, item.title] if group else item.section
            scope = detachment_id
            href_base = f"/codices/{codex_id}/detachments/{detachment_id}/rules/"

        rule_id = unique(slug(item.title), taken.setdefault(scope, set()))
        rule = base_rule(
            seg, rule_id=rule_id, layer="codex", kind=kind, name=item.title,
            section=section, href=href_base + rule_id, url=url, page=f"faction/{codex_id}",
        )
        rule["anchors"] += pending
        pending = []
        rule["codex_id"] = codex_id
        rule["detachment_id"] = detachment_id
        rules.append(rule)

    return source, list(detachments.values()), rules, datasheet_links(soup, codex_id)


# --------------------------------------------------------------------------- #
# datasheets
# --------------------------------------------------------------------------- #

def _cell(tag: Tag | None) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


def _profiles(ds: Tag, title: str, base: str) -> list[str]:
    """Una linea por perfil. Las unidades de un solo modelo no nombran el
    perfil y llevan la peana en el titulo de la datasheet."""
    labels = [_cell(c) for c in ds.select(".dsCharName")]
    lines = []
    for wrap in ds.select("div.dsProfileBaseWrap"):
        values = [_cell(v) for v in wrap.select(".dsCharValue")]
        model = _cell(wrap.select_one(".dsModelName")) or title
        size = _cell(wrap.select_one(".dsModelBase")) or base
        stats = ", ".join(f"{k} {v}" for k, v in zip(labels, values))
        lines.append(f"- {model} {size}: {stats}".replace("  ", " "))
    invuln = ds.select_one(".dsCharInvul")
    if invuln is not None:
        lines.append(f"- Invulnerable save: {_cell(invuln)}")
    return lines


def _weapons(ds: Tag, tooltips: dict[str, str], links: list[str]) -> list[str]:
    """Armas a distancia y cuerpo a cuerpo. Vienen en una misma tabla, con una
    fila de encabezado (icono + columnas) antes de cada grupo."""
    out = []
    for table in ds.select("table.wTable"):
        for row in table.select("tr"):
            classes = set(row.get("class") or [])
            if row.select_one(".dsHeader") is not None:
                melee = row.select_one(".dsMeleeIcon") is not None
                labels = [_cell(h) for h in row.select("div.ct.dsHeader")]
                out.append(f"\n**{'Melee' if melee else 'Ranged'} weapons** ({' / '.join(labels)})")
            elif "dsWeaponRow" in classes:
                cell = row.select_one("td.wTable2_short")
                name = _cell(cell.select_one(".dsWeaponName")) if cell else ""
                keywords = [_cell(k) for k in cell.select("span.kwbw")] if cell else []
                for kw in cell.select("[data-tooltip-content]") if cell else []:
                    tooltip = kw["data-tooltip-content"].lstrip("#")
                    if tooltip in tooltips:
                        links.append(tooltips[tooltip])
                values = [_cell(v) for v in row.select("div.ct")]
                tags = f" [{', '.join(keywords)}]" if keywords else ""
                out.append(f"- {name}{tags}: {' / '.join(values)}")
            elif "wTable2_long" not in classes:
                note = _cell(row)
                if note:  # texto aclaratorio entre perfiles
                    out.append(f"  {note}")
    return out


def parse_datasheet(html: str, codex_id: str, name: str) -> dict | None:
    url = fetch.url_for(f"factions/{codex_id}/{name}")
    soup = soup_of(html)
    ds = soup.select_one("div.datasheet")
    if ds is None:
        return None
    conv = Converter(tooltip_links(soup))
    links: list[str] = []

    def render(nodes: list[Tag]) -> str:
        seg = conv.render(nodes)
        links.extend(seg.links)
        return seg.text

    header = _cell(ds.select_one(".dsH2Header"))
    base = re.search(r"\(⌀[^)]*\)", header)
    title = re.sub(r"\s*\(⌀[^)]*\)\s*", " ", header).strip()
    lines = [
        "**Profiles**",
        *_profiles(ds, title, base.group(0) if base else ""),
        *_weapons(ds, conv.tooltips, links),
    ]

    for row in ds.select("table.dsCoreArmy tr"):  # "CORE: Leader", "ARMY RULES: ..."
        label, value = row.select_one(".dsCoreArmyLabel"), row.select_one(".dsCoreArmyValue")
        if label is not None and value is not None:
            lines.append(f"\n**{_cell(label).title()}:** {render([value]).strip()}")

    costs: dict[str, str] = {}
    for row in ds.select("tr"):
        price = row.select_one(".PriceTag")
        cells = row.find_all("td")
        if price is not None and cells:
            costs.setdefault(_cell(cells[0]), _cell(price))
    for table in ds.select("table"):
        if table.select_one(".dsUnitCostHeader"):
            table.decompose()

    for header in ds.select("div.dsHeader"):
        if header.find_parent("table"):
            continue
        label = _cell(header)
        if not label or label in DATASHEET_SKIP:
            continue
        body = []
        for sibling in header.find_next_siblings():
            if "dsHeader" in (sibling.get("class") or []) or sibling.select_one("div.dsHeader"):
                break  # la seccion siguiente, aunque venga anidada
            body.append(sibling)
        text = render(body)
        if text:
            lines.append(f"\n**{label.title()}**\n{text}")

    if costs:
        lines.append("\n**Points:** " + "; ".join(f"{k}: {v} pts" for k, v in costs.items()))
    keywords = ds.select_one(".ds2colKWFlat")
    if keywords is not None:
        lines.append("\n" + render([keywords]))

    seg = Segment(anchor="", parts=["\n".join(lines)], links=links)
    rule_id = slug(name)
    rule = base_rule(
        seg, rule_id=rule_id, layer="codex", kind="datasheet", name=title,
        section=["Datasheets", title], href=f"/codices/{codex_id}/rules/{rule_id}",
        url=url, page=f"datasheet/{codex_id}/{name}",
    )
    rule["source_url"] = url
    rule["codex_id"] = codex_id
    rule["detachment_id"] = None
    return rule
