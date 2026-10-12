"""HTML de Wahapedia -> Markdown liviano, partido en segmentos por ancla.

Cada `<a name="...">` del cuerpo abre un segmento nuevo: es la unidad que
despues se guarda como regla. Mientras recorre, el conversor junta:

- los enlaces que aparecen en el texto (directos o via tooltip), que se
  resuelven despues a `references`;
- los diagramas (solo si se pide, para core rules), con su titulo y el
  recuadro explicativo que Wahapedia pone debajo.

Se descarta lo que no es regla: publicidad, texto de ambientacion
(`ShowFluff`), el indice y las plantillas de tooltips.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCKS = HEADINGS | {"div", "p", "ul", "ol", "table", "tbody", "tr", "section", "blockquote"}
DROP_TAGS = {"script", "style", "noscript", "iframe", "ins", "svg"}
SKIP_CLASSES = {
    "noprint", "page_breaker_ads", "ShowFluff", "tooltip_templates",
    "contentsWrap", "faqErrataHead", "str11Bg", "picLegend", "img-inv",
    "h_number", "h_number_red", "h_number_red2", "dpPts", "h_img11", "tooltipSelectionWarning",
}
# imagenes de interfaz que no son diagramas de reglas
UI_IMAGE_RE = re.compile(r"logo|icon|arrow|/expansions/|/fd[A-Z]", re.IGNORECASE)


@dataclass
class Segment:
    anchor: str
    title: str = ""
    number: str = ""
    parts: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    figures: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return tidy("".join(self.parts))


def soup_of(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(list(DROP_TAGS)):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    return soup


def tooltip_links(soup: BeautifulSoup) -> dict[str, str]:
    """id de plantilla de tooltip -> href de la regla que describe.

    Solo cuentan las plantillas que apuntan a una regla (tienen el boton
    `tooltip_link`); las de keywords listan datasheets y se ignoran.
    """
    links: dict[str, str] = {}
    for template in soup.select("div.tooltip_templates [id^=tooltip_content]"):
        button = template.select_one("a[href] > div.tooltip_link")
        if button is not None:
            links[template["id"]] = button.parent["href"]
    return links


def heading_text(tag: Tag) -> str:
    """Texto del encabezado sin la numeracion ni los adornos."""
    tag = copy.copy(tag)
    for extra in tag.find_all(class_=lambda c: c in SKIP_CLASSES):
        extra.decompose()
    return re.sub(r"\s+", " ", tag.get_text(" ")).strip()


def enhancement_name(pts: Tag) -> tuple[str, bool]:
    """Nombre de una mejora (`ul.EnhancementsPts`) y si es de tipo UPGRADE,
    que Wahapedia marca con una etiqueta pegada al nombre."""
    span = pts.select_one("li > span")
    if span is None:
        return "", False
    span = copy.copy(span)
    badge = span.select_one(".EnhUpgrade")
    if badge is not None:
        badge.decompose()
    return span.get_text(" ", strip=True), badge is not None


def tidy(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n- *\n", "\n", text)             # bullets vacios
    text = re.sub(r"(?m)^(Q|A): *\n+", r"\1: ", text)  # FAQ en una linea
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\n\n(?=- )", "\n", text)          # listas sin renglon vacio
    return text.strip()


class Converter:
    def __init__(self, tooltips: dict[str, str] | None = None, figures: bool = False):
        self.tooltips = tooltips or {}
        self.figures = figures
        self.segments: list[Segment] = []
        self.cur = Segment(anchor="")

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #

    def split(self, root: Tag) -> list[Segment]:
        """Recorre `root` y devuelve un segmento por ancla, en orden."""
        self.segments = []
        self.cur = Segment(anchor="")
        self.walk(root)
        segments: list[Segment] = []
        for seg in self.segments:
            if not seg.anchor:
                continue
            if seg.title.lower() == "see also" and segments:
                # lista de referencias con ancla propia: es de la regla anterior
                segments[-1].parts += ["\n\n**See also:**\n", *seg.parts]
                segments[-1].links += seg.links
                continue
            segments.append(seg)
        return segments

    def render(self, nodes: list[Tag]) -> Segment:
        """Convierte nodos sueltos a un unico segmento (para datasheets)."""
        self.cur = Segment(anchor="_")
        for node in nodes:
            self.walk(node)
        return self.cur

    # ------------------------------------------------------------------ #
    # recorrido
    # ------------------------------------------------------------------ #

    def emit(self, text: str) -> None:
        self.cur.parts.append(text)

    def block(self, text: str = "") -> None:
        self.emit(f"\n{text}\n" if text else "\n")

    def start(self, anchor: str, meta: dict | None = None) -> None:
        self.cur = Segment(anchor=anchor, meta=dict(meta or {}))
        self.segments.append(self.cur)

    def walk(self, node) -> None:
        if isinstance(node, NavigableString):
            self.emit(re.sub(r"\s+", " ", str(node)))
            return
        if not isinstance(node, Tag) or node.name in DROP_TAGS:
            return
        classes = set(node.get("class") or [])
        if classes & SKIP_CLASSES:
            return

        name = node.name
        if name == "a" and node.get("name") is not None and not node.get("href"):
            meta = {"kind": node["data-kind"]} if node.get("data-kind") else None
            self.start(node["name"], meta)
            return
        if name in HEADINGS:
            self.heading(node)
            return
        if name == "img":
            self.image(node)
            return
        if "str11Name" in classes:  # bloque de estratagema o de move type
            if not self.cur.title:
                self.cur.title = heading_text(node).title()
                number = node.select_one(".h_number")
                if number is not None:
                    self.cur.number = number.get_text(strip=True)
            return
        if "str11Type" in classes:  # "Gladius Task Force Stratagem"
            kind = node.get_text(" ", strip=True)
            if "stratagem" in kind.lower():
                self.cur.meta["kind"] = "stratagem"
            self.block(kind)
            return
        if "str11CP" in classes:
            self.block(f"**Cost:** {node.get_text(strip=True)}")
            return
        if "EnhancementsPts" in classes:
            name, upgrade = enhancement_name(node)
            if name and not self.cur.title:
                self.cur.title = name
            spans = node.select("li > span")
            if len(spans) > 1:
                self.block(f"**Cost:** {spans[1].get_text(' ', strip=True)}")
            if upgrade:
                self.block("**Type:** Upgrade")
            return
        if "faqErrataSpoiler" in classes:
            self.block("**Errata / FAQ:**")
        if "errata_H" in classes or "bcHeader" in classes:
            self.block(f"**{node.get_text(' ', strip=True)}**")
            return
        if "faq_Q" in classes or "faq_A" in classes:
            self.emit("\n" + node.get_text(strip=True) + " ")
            return

        if name == "br":
            self.emit("\n")
            return
        if name == "li":
            self.emit("\n- ")
            self.children(node)
            self.emit("\n")
            return
        if name == "td":
            self.children(node)
            self.emit(" ")
            return
        if name in ("b", "strong") and not node.find_parent(["b", "strong"]):
            self.bold(node)
            return

        href = node.get("href") if name == "a" else None
        if href and not href.startswith(("javascript", "mailto")):
            self.cur.links.append(href)
        tooltip = node.get("data-tooltip-content", "").lstrip("#")
        if tooltip in self.tooltips:
            self.cur.links.append(self.tooltips[tooltip])

        is_block = name in BLOCKS
        if is_block:
            self.emit("\n")
        self.children(node)
        if is_block:
            self.emit("\n")

    def children(self, node: Tag) -> None:
        for child in list(node.children):
            self.walk(child)

    def bold(self, node: Tag) -> None:
        segment, start = self.cur, len(self.cur.parts)
        self.children(node)
        if self.cur is not segment:  # se abrio un ancla adentro: no envolver
            return
        inner = "".join(segment.parts[start:])
        del segment.parts[start:]
        stripped = inner.strip()
        if stripped:
            lead = " " if inner[:1].isspace() else ""
            trail = " " if inner[-1:].isspace() else ""
            segment.parts.append(f"{lead}**{stripped}**{trail}")

    def heading(self, node: Tag) -> None:
        title = heading_text(node)
        if not self.cur.title and not "".join(self.cur.parts).strip():
            self.cur.title = title
            number = node.select_one(".h_number, .h_number_red, .h_number_red2")
            if number is not None:
                self.cur.number = number.get_text(strip=True)
            return
        if title:
            self.block(f"\n**{title}**\n")

    def image(self, node: Tag) -> None:
        src = node.get("src", "")
        if not self.figures or "/img/" not in src or UI_IMAGE_RE.search(src):
            return
        caption_tag = node.find_next_sibling(class_="h_img11")
        caption = caption_tag.get_text(" ", strip=True) if caption_tag else None
        frame = node.find_parent(class_="img-opa")
        box = frame.find_next_sibling(class_="Corner36") if frame else None
        description = tidy(box.get_text(" ", strip=True)) if box else None
        self.cur.figures.append({
            "src": src,
            "caption": caption.capitalize() if caption else None,
            "description": description or None,
        })
        self.block(f"[Diagram: {caption.capitalize()}]" if caption else "[Diagram]")
