"""Testa se a JamBase acha shows num país para uma lista de artistas.

Uso:
    set JAMBASE_API_KEY=...            (PowerShell: $env:JAMBASE_API_KEY = "...")
    python jambase_coverage_test.py "Artista 1" "Artista 2" [--country BR]

Sem artistas, usa os casos de teste do projeto.
"""

import argparse
import os
import sys

from artist_sync import Http, HttpError
from jambase import JamBase, summarize

DEFAULT_ARTISTS = ["toe", "Mass of the Fermenting Dregs", "Coldplay"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("artists", nargs="*", default=DEFAULT_ARTISTS)
    ap.add_argument("--country", default="BR")
    ap.add_argument("--no-past", action="store_true", help="não buscar shows do último ano")
    args = ap.parse_args(argv)

    key = os.environ.get("JAMBASE_API_KEY")
    if not key:
        print("ERRO: defina a variável JAMBASE_API_KEY", file=sys.stderr)
        return 2
    jb = JamBase(key, Http())

    rows = []
    for name in args.artists:
        try:
            found = jb.find_artists(name)
        except HttpError as e:
            print(f"ERRO na JamBase: {e}", file=sys.stderr)
            return 1
        if not found:
            print(f"=== {name}: nenhum artista com esse nome exato na JamBase\n")
            rows.append((name, "-", "-", "-"))
            continue
        ids = [a["identifier"] for a in found]
        upcoming_world = sum(a.get("x-numUpcomingEvents") or 0 for a in found)
        print(f"=== {name} [{', '.join(ids)}] - futuros no mundo: {upcoming_world}")

        counts = []
        for label, past in (("futuros", False), ("último ano", True)):
            if past and args.no_past:
                counts.append("-")
                continue
            # Sem shows futuros no mundo, não há por que gastar cota buscando futuros no país.
            events = [] if (not past and upcoming_world == 0) else jb.events(ids, args.country, past=past)
            counts.append(str(len(events)))
            print(f"  {label} em {args.country}: {len(events)}")
            for e in map(summarize, events):
                print(f"    {e['date']} | {e['venue']}, {e['city']} | {e['url']}")
        rows.append((name, ", ".join(ids), *counts))
        print()

    print(f"===== RESUMO ({args.country}) =====")
    width = max(len(r[0]) for r in rows)
    print(f"{'Artista':<{width}}  Futuros  Último ano  ID")
    for name, ids, fut, past in rows:
        print(f"{name:<{width}}  {fut:>7}  {past:>10}  {ids}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
