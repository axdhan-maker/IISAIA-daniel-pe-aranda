"""Sincroniza las reglas desde Wahapedia.

    python -m wahapedia sync                    core + space-marines + orks
    python -m wahapedia sync --codex orks       core + solo ese codex
    python -m wahapedia sync --no-core          solo los codex
    python -m wahapedia sync --refresh          ignora la cache de HTML

Sin --refresh se usa el HTML ya descargado en data/wahapedia/raw/, asi que
re-generar el almacen tras cambiar el parser no vuelve a pedir nada.
"""

from __future__ import annotations

import argparse
import sys

from . import fetch, parse, store

DEFAULT_CODICES = ["space-marines", "orks"]


def scrape_core(refresh: bool) -> list[dict]:
    rules = []
    for key, (path, _, _) in parse.CORE_PAGES.items():
        rules += parse.parse_core(fetch.get(fetch.url_for(path), refresh), key)
    return rules


def scrape_codex(codex_id: str, refresh: bool, datasheets: bool):
    html = fetch.get(fetch.url_for(f"factions/{codex_id}/"), refresh)
    source, detachments, rules, names = parse.parse_codex(html, codex_id)
    if not datasheets:
        return source, detachments, rules

    taken = {r["id"] for r in rules if r["detachment_id"] is None}
    for n, name in enumerate(names, start=1):
        print(f"\r  {codex_id}: datasheet {n}/{len(names)}", end="", flush=True)
        page = fetch.get(fetch.url_for(f"factions/{codex_id}/{name}"), refresh)
        rule = parse.parse_datasheet(page, codex_id, name)
        if rule is None:
            continue
        rule_id = parse.unique(rule["id"], taken)
        rule["id"], rule["href"] = rule_id, f"/codices/{codex_id}/rules/{rule_id}"
        rules.append(rule)
    print()
    return source, detachments, rules


def sync(codices: list[str], core: bool, refresh: bool, datasheets: bool) -> None:
    scraped_at = store.now()
    parsed_core = scrape_core(refresh) if core else []
    parsed = {cid: scrape_codex(cid, refresh, datasheets) for cid in codices}

    syncing = set(codices) | ({"core"} if core else set())
    fresh = parsed_core + [r for _, _, rules in parsed.values() for r in rules]
    unresolved = store.resolve_references(fresh, store.saved_rules(exclude=syncing))

    if core:
        print("core:", store.save_core(parsed_core, scraped_at), f"({len(parsed_core)} reglas)")
    for cid, (source, detachments, rules) in parsed.items():
        changes = store.save_codex(source, detachments, rules, scraped_at)
        print(f"{cid}:", changes, f"({len(rules)} reglas, {len(detachments)} destacamentos)")
    print(f"enlaces sin resolver (otra faccion o encabezado sin texto): {unresolved}")
    print(f"-> {store.DATA_DIR}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m wahapedia")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("sync", help="scrapea Wahapedia y regenera el almacen y el indice")
    cmd.add_argument("--codex", action="append", help="id del codex (repetible)")
    cmd.add_argument("--no-core", action="store_true", help="no sincronizar core rules")
    cmd.add_argument("--no-datasheets", action="store_true", help="omitir datasheets")
    cmd.add_argument("--refresh", action="store_true", help="volver a descargar el HTML")
    args = parser.parse_args(argv)

    if args.command == "sync":
        sync(
            codices=args.codex or DEFAULT_CODICES,
            core=not args.no_core,
            refresh=args.refresh,
            datasheets=not args.no_datasheets,
        )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
