"""Cruza os artistas conhecidos com a JamBase e guarda os shows no país.

A cota gratuita da JamBase é de 1.000 chamadas/mês, então cada execução
gasta no máximo --budget chamadas e checa primeiro os artistas que estão
há mais tempo sem checagem. Com ~150 artistas e 30 chamadas/dia, cada um
é revisto a cada ~5 dias.

Custo por artista: 1 chamada para achar o ID na JamBase (só na primeira
vez, guardado depois) + 1 chamada para os eventos no país.

Uso:
    python shows.py check [--country BR] [--budget 30]
"""

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from artist_sync import STATE_DIR, Http, HttpError, load_json, save_json
from jambase import JamBase, summarize

DAILY_BUDGET = 30
MONTHLY_CAP = 1000
RESOLVE_RETRY_DAYS = 30   # artista não achado na JamBase é procurado de novo depois disso


def _queue(artists, checks):
    """Artistas não silenciados, do checado há mais tempo (ou nunca) ao mais recente."""
    keys = [k for k, a in artists.items() if not a.get("muted")]
    return sorted(keys, key=lambda k: (checks.get(k, {}).get("last_checked") or "", k))


def check_shows(state, shows, jb, today, country="BR", budget=DAILY_BUDGET, monthly_cap=MONTHLY_CAP):
    """Atualiza `shows` e devolve (shows novos, chamadas gastas)."""
    checks = shows.setdefault("checks", {})
    events = shows.setdefault("events", {})
    usage = shows.setdefault("usage", {})
    today_s = today.isoformat()
    month = today_s[:7]
    budget = max(0, min(budget, monthly_cap - usage.get(month, 0)))
    retry_before = (today - dt.timedelta(days=RESOLVE_RETRY_DAYS)).isoformat()
    used = 0
    new = []

    for key in _queue(state.get("artists", {}), checks):
        artist = state["artists"][key]
        c = checks.setdefault(key, {})
        needs_resolve = "jambase_ids" not in c or (not c["jambase_ids"] and c.get("resolved_on", "") < retry_before)
        if not needs_resolve and not c["jambase_ids"]:
            continue   # não existe na JamBase; tenta de novo daqui a RESOLVE_RETRY_DAYS
        if used + needs_resolve + 1 > budget:
            break

        if needs_resolve:
            found = jb.find_artists(artist["name"])
            used += 1
            c["jambase_ids"] = [a["identifier"] for a in found]
            c["resolved_on"] = today_s
            # Sem show futuro em lugar nenhum: não gasta a chamada de eventos.
            if not found or sum(a.get("x-numUpcomingEvents") or 0 for a in found) == 0:
                c["last_checked"] = today_s
                continue

        found_events = jb.events(c["jambase_ids"], country, max_pages=1)
        used += 1
        c["last_checked"] = today_s
        for e in found_events:
            eid = e.get("identifier")
            if not eid:
                continue
            info = {**summarize(e), "status": e.get("eventStatus", ""), "artist": artist["name"], "artist_key": key}
            if eid in events:
                events[eid].update(info)
            else:
                events[eid] = {**info, "first_seen": today_s}
                new.append(events[eid])

    for eid in [eid for eid, e in events.items() if e["date"] < today_s]:
        del events[eid]

    usage[month] = usage.get(month, 0) + used
    shows["last_run"] = today_s
    shows["country"] = country
    return new, used


def main(argv=None):
    ap = argparse.ArgumentParser(description="Busca shows dos seus artistas na JamBase.")
    ap.add_argument("--state-dir", default=str(STATE_DIR))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="checa um lote de artistas")
    p.add_argument("--country", default=os.environ.get("ACHASHOW_COUNTRY", "BR"))
    p.add_argument("--budget", type=int, default=int(os.environ.get("JAMBASE_DAILY_BUDGET", DAILY_BUDGET)))
    args = ap.parse_args(argv)

    key = os.environ.get("JAMBASE_API_KEY")
    if not key:
        print("ERRO: defina a variável JAMBASE_API_KEY", file=sys.stderr)
        return 2

    state_dir = Path(args.state_dir)
    state = load_json(state_dir / "artists.json", {})
    if not state.get("artists"):
        print("ERRO: nenhum artista ainda; rode `artist_sync.py sync` antes", file=sys.stderr)
        return 2
    shows_path = state_dir / "shows.json"
    shows = load_json(shows_path, {})

    try:
        new, used = check_shows(state, shows, JamBase(key, Http()), dt.date.today(),
                                country=args.country, budget=args.budget)
    finally:
        # Salva o que já foi checado mesmo se a JamBase falhar no meio.
        save_json(shows_path, shows)

    month = dt.date.today().isoformat()[:7]
    print(f"{used} chamadas à JamBase ({shows['usage'][month]}/{MONTHLY_CAP} no mês).")
    if new:
        print(f"{len(new)} show(s) novo(s):")
        for e in sorted(new, key=lambda e: e["date"]):
            print(f"  - {e['date']} {e['artist']} | {e['venue']}, {e['city']} | {e['url']}")
    else:
        print("Nenhum show novo.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HttpError as e:
        print(f"ERRO na JamBase: {e}", file=sys.stderr)
        sys.exit(1)
