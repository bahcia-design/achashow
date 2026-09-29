"""Procura anúncios de show no Brasil no Google Notícias (RSS, sem conta).

Cobre o que a JamBase não pega: banda pequena em casa pequena costuma
aparecer primeiro em sites de música brasileiros (Tenho Mais Discos Que
Amigos, Billboard Brasil, sonoridadeunderground...).

Uma notícia conta quando o título tem o nome exato do artista, uma
palavra de anúncio (anuncia, confirma, ingressos, turnê...) e um lugar
do Brasil (Brasil, São Paulo, Curitiba, Rock in Rio...).
Como o mesmo show sai em vários sites, o aviso é um por artista: depois
de avisar, aquele artista só gera aviso de novo passados REALERT_DAYS.
Não precisa de chave nem de conta; só espera PAUSE segundos entre buscas.

Uso:
    python news.py check [--limit N]
"""

import argparse
import datetime as dt
import email.utils
import re
import sys
import time
import xml.etree.ElementTree as ET

from artist_sync import STATE_DIR, Http, HttpError, load_json, norm, save_json

RSS_URL = "https://news.google.com/rss/search"
ANNOUNCE = ("anuncia", "confirma", "retorna", "volta ao brasil", "vem ao brasil", "chega ao brasil",
            "estreia em", "estreia no brasil", "ingresso", "pré-venda", "pre-venda", "venda geral",
            "show extra", "show único", "data extra", "novas datas", "turnê", "turne", "line-up",
            "lineup", "escalado", "atração")
MAX_AGE_DAYS = 45     # notícia mais velha que isso não é aviso novo
KEEP_DAYS = 120       # quanto tempo as notícias ficam guardadas
BR_PLACES = ("brasil", "brasileir", "são paulo", "sao paulo", " sp", "rio de janeiro", " rio",
             "belo horizonte", " bh", "curitiba", "porto alegre", "brasília", "brasilia", "salvador",
             "recife", "fortaleza", "florianópolis", "florianopolis", "goiânia", "goiania", "campinas",
             "belém", "manaus", "vitória", "santos", "rock in rio", "lollapalooza", "the town",
             "knotfest", "primavera sound", "bangers open air", "summer breeze")
SHORT_NAME = 4        # nomes até este tamanho precisam bater maiúsculas ("Sou" não casa com "sou")
REALERT_DAYS = 21   # mesmo artista só gera aviso novo depois disso
PAUSE = 1.5


def query_for(name):
    return f'"{name}" (show OR turnê OR ingressos OR festival) Brasil'


def parse_rss(xml_text):
    items = []
    for it in ET.fromstring(xml_text).iter("item"):
        pub = it.findtext("pubDate")
        try:
            date = email.utils.parsedate_to_datetime(pub).date() if pub else None
        except (TypeError, ValueError):
            date = None
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        # O Google Notícias põe " - Nome do Site" no fim; tira para não confundir o filtro
        # (ex.: "Billboard Brasil" fazia qualquer notícia parecer brasileira).
        if " - " in title:
            title = title.rsplit(" - ", 1)[0].strip()
        items.append({
            "title": title,
            "link": (it.findtext("link") or "").strip(),
            "source": source,
            "date": date.isoformat() if date else "",
        })
    return items


def _has_word(text, word):
    return re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text) is not None


def relevant(title, name):
    t, n = norm(title), norm(name)
    if len(n) <= SHORT_NAME:
        # Nome curto costuma ser palavra comum: exige a grafia do artista ou tudo maiúsculo.
        if not (_has_word(title, name.strip()) or _has_word(title, name.strip().upper())):
            return False
    elif not _has_word(t, n):
        return False
    padded = " " + t
    return any(k in t for k in ANNOUNCE) and any(p in padded for p in BR_PLACES)


def check_news(state, news, http, today, sleep=time.sleep, limit=None):
    """Atualiza `news` e devolve os avisos novos (no máximo um por artista)."""
    items = news.setdefault("items", {})
    last_alert = news.setdefault("last_alert", {})
    realert_from = (today - dt.timedelta(days=REALERT_DAYS)).isoformat()
    today_s = today.isoformat()
    oldest = (today - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    artists = [a for a in state.get("artists", {}).values() if not a.get("muted")]
    artists.sort(key=lambda a: norm(a["name"]))
    alerts = []

    for i, artist in enumerate(artists[:limit]):
        if i:
            sleep(PAUSE)
        _, body = http.request("GET", RSS_URL, headers={"Accept": "application/rss+xml"},
                               params={"q": query_for(artist["name"]), "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})
        if not isinstance(body, str):
            continue
        found = []
        for it in parse_rss(body):
            if not it["link"] or it["link"] in items or it["date"] < oldest:
                continue
            if not relevant(it["title"], artist["name"]):
                continue
            items[it["link"]] = {**it, "artist": artist["name"], "first_seen": today_s}
            found.append(items[it["link"]])
        key = norm(artist["name"])
        if found and last_alert.get(key, "") < realert_from:
            last_alert[key] = today_s
            top = max(found, key=lambda n: n["date"])
            alerts.append({**top, "count": len(found)})

    keep_from = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for link in [k for k, v in items.items() if v["first_seen"] < keep_from]:
        del items[link]
    news["last_run"] = today_s
    return alerts


def main(argv=None):
    ap = argparse.ArgumentParser(description="Procura anúncios de show no Google Notícias.")
    ap.add_argument("--state-dir", default=str(STATE_DIR))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="procura notícias de todos os artistas")
    p.add_argument("--limit", type=int, help="só os N primeiros artistas (para teste)")
    args = ap.parse_args(argv)

    state = load_json(f"{args.state_dir}/artists.json", {})
    if not state.get("artists"):
        print("ERRO: nenhum artista ainda; rode `artist_sync.py sync` antes", file=sys.stderr)
        return 2
    news_path = f"{args.state_dir}/news.json"
    news = load_json(news_path, {})
    try:
        new = check_news(state, news, Http(), dt.date.today(), limit=args.limit)
    finally:
        save_json(news_path, news)

    if new:
        print(f"{len(new)} notícia(s) nova(s) de show:")
        for n in sorted(new, key=lambda n: n["date"], reverse=True):
            print(f"  - [{n['artist']}] {n['title']} ({n['date']})\n    {n['link']}")
    else:
        print("Nenhuma notícia nova de show.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HttpError as e:
        print(f"ERRO no Google Notícias: {e}", file=sys.stderr)
        sys.exit(1)
