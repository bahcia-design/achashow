"""Detecta sozinho os artistas que eu ouço (Spotify ou ListenBrainz).

A primeira execução de `sync` grava uma linha de base em silêncio. Depois
disso, cada artista novo é avisado uma única vez, quando passa a contar
como "meu": sigo o artista, ele aparece num top, ou tem pelo menos
MIN_PLAYS reproduções (evita alarme falso de playlist de terceiros).

Só biblioteca padrão do Python.

Uso:
    python artist_sync.py spotify-auth --client-id SEU_CLIENT_ID
    python artist_sync.py sync [--source spotify|listenbrainz]
    python artist_sync.py list
    python artist_sync.py mute "Nome do Artista"
    python artist_sync.py unmute "Nome do Artista"
"""

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

USER_AGENT = "achashow/0.1 (+https://github.com/bahcia-design/achashow)"
DATA_DIR = Path(os.environ.get("ACHASHOW_DATA", Path(__file__).resolve().parent / "data"))

MIN_PLAYS = 2
PENDING_DAYS = 90             # reproduções soltas mais velhas que isso são esquecidas
REFRESH_TTL_DAYS = 182        # refresh token do Spotify vale 6 meses desde a autorização
REAUTH_WARN_DAYS = 30

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_SCOPES = "user-top-read user-follow-read user-read-recently-played"
LISTENBRAINZ_API = "https://api.listenbrainz.org/1"


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def _decode(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


class Http:
    """Cliente HTTP mínimo: JSON na volta e nova tentativa em 429."""

    def __init__(self, sleep=time.sleep, max_retries=4, timeout=30):
        self.sleep = sleep
        self.max_retries = max_retries
        self.timeout = timeout

    def request(self, method, url, params=None, headers=None, data=None):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        if body is not None:
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.status, _decode(resp.read())
            except urllib.error.HTTPError as e:
                raw = e.read()
                if e.code == 429 and attempt < self.max_retries:
                    try:
                        wait = float(e.headers.get("Retry-After"))
                    except (TypeError, ValueError):
                        wait = 2 ** attempt
                    self.sleep(min(wait, 120))
                    continue
                raise HttpError(e.code, _decode(raw)) from None


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def norm(name):
    """Chave de comparação de nomes: sem diferença de caixa/espaços/Unicode."""
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def pkce_challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# --------------------------------------------------------------------------
# Spotify
# --------------------------------------------------------------------------

class ReauthRequired(Exception):
    """O login do Spotify precisa ser refeito (token ausente ou expirado)."""


class Spotify:
    def __init__(self, client_id, http, token_path, now=time.time):
        self.client_id = client_id
        self.http = http
        self.token_path = Path(token_path)
        self.now = now
        self.token = load_json(self.token_path, None)

    def _store(self, resp, authorized_at):
        tok = dict(self.token or {})
        tok["access_token"] = resp["access_token"]
        tok["expires_at"] = self.now() + int(resp.get("expires_in", 3600))
        if resp.get("refresh_token"):
            tok["refresh_token"] = resp["refresh_token"]
        tok["authorized_at"] = authorized_at
        self.token = tok
        save_json(self.token_path, tok)

    def exchange_code(self, code, verifier, redirect_uri):
        _, resp = self.http.request("POST", SPOTIFY_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        })
        self._store(resp, authorized_at=self.now())

    def refresh(self):
        if not self.token or not self.token.get("refresh_token"):
            raise ReauthRequired("sem login do Spotify: rode `spotify-auth`")
        try:
            _, resp = self.http.request("POST", SPOTIFY_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": self.token["refresh_token"],
                "client_id": self.client_id,
            })
        except HttpError as e:
            if e.status == 400 and isinstance(e.body, dict) and e.body.get("error") == "invalid_grant":
                raise ReauthRequired("login do Spotify expirou: rode `spotify-auth` de novo") from None
            raise
        # A validade de 6 meses conta da autorização original, não da renovação.
        self._store(resp, authorized_at=self.token.get("authorized_at", self.now()))

    def days_until_reauth(self):
        if not self.token or "authorized_at" not in self.token:
            return None
        return (self.token["authorized_at"] + REFRESH_TTL_DAYS * 86400 - self.now()) / 86400

    def get(self, path, params=None):
        if not self.token:
            raise ReauthRequired("sem login do Spotify: rode `spotify-auth`")
        if self.now() >= self.token.get("expires_at", 0) - 60:
            self.refresh()
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self.token['access_token']}"}
            try:
                return self.http.request("GET", SPOTIFY_API + path, params=params, headers=headers)[1]
            except HttpError as e:
                if e.status == 401 and attempt == 0:
                    self.refresh()
                    continue
                raise


def spotify_login(sp, port=8888, open_browser=webbrowser.open, timeout=300):
    """Login Authorization Code + PKCE com callback em 127.0.0.1."""
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(16)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()})
            ok = result.get("state") == state and "code" in result
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Login feito, pode fechar esta aba." if ok else "Falha no login, veja o terminal."
            self.wfile.write(f"<p>{msg}</p>".encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/callback"
    auth_url = SPOTIFY_AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": sp.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": pkce_challenge(verifier),
        "scope": SPOTIFY_SCOPES,
        "state": state,
    })
    print(f"Abrindo o navegador. Se não abrir, acesse:\n{auth_url}\n")
    try:
        open_browser(auth_url)
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    if not result:
        raise RuntimeError("tempo esgotado esperando o login do Spotify")
    if "error" in result:
        raise RuntimeError(f"Spotify recusou o login: {result['error']}")
    if result.get("state") != state:
        raise RuntimeError("state inválido no retorno do Spotify")
    sp.exchange_code(result["code"], verifier, redirect_uri)


# --------------------------------------------------------------------------
# Coleta de sinais
# --------------------------------------------------------------------------

class Signals:
    """O que uma fonte diz sobre cada artista nesta execução."""

    def __init__(self):
        self.artists = {}

    def _get(self, name, ext_id):
        a = self.artists.setdefault(norm(name), {"name": name, "ids": set(), "reasons": set(), "plays": set()})
        if ext_id:
            a["ids"].add(ext_id)
        return a

    def add(self, name, ext_id, reason):
        self._get(name, ext_id)["reasons"].add(reason)

    def play(self, name, ext_id, played_at):
        self._get(name, ext_id)["plays"].add(str(played_at))


def spotify_signals(sp):
    sig = Signals()
    for rng in ("short_term", "medium_term", "long_term"):
        data = sp.get("/me/top/artists", {"time_range": rng, "limit": 50})
        for a in data.get("items", []):
            sig.add(a["name"], "spotify:" + a["id"], f"top:{rng}")

    after = None
    while True:
        params = {"type": "artist", "limit": 50}
        if after:
            params["after"] = after
        page = sp.get("/me/following", params)["artists"]
        for a in page.get("items", []):
            sig.add(a["name"], "spotify:" + a["id"], "segue")
        after = (page.get("cursors") or {}).get("after")
        if not after or not page.get("next"):
            break

    data = sp.get("/me/player/recently-played", {"limit": 50})
    for item in data.get("items", []):
        for a in item["track"]["artists"]:
            sig.play(a["name"], "spotify:" + a["id"], item["played_at"])
    return sig


def listenbrainz_signals(user, http):
    sig = Signals()
    user_q = urllib.parse.quote(user, safe="")
    for rng in ("month", "half_yearly", "all_time"):
        status, data = http.request("GET", f"{LISTENBRAINZ_API}/stats/user/{user_q}/artists",
                                    params={"range": rng, "count": 50})
        if status == 204 or not data:   # estatística ainda não calculada
            continue
        for a in data["payload"].get("artists", []):
            mbid = a.get("artist_mbid") or next(iter(a.get("artist_mbids") or []), None)
            sig.add(a["artist_name"], f"mbid:{mbid}" if mbid else None, f"top:{rng}")

    _, data = http.request("GET", f"{LISTENBRAINZ_API}/user/{user_q}/listens", params={"count": 200})
    for listen in (data or {}).get("payload", {}).get("listens", []):
        sig.play(listen["track_metadata"]["artist_name"], None, listen["listened_at"])
    return sig


# --------------------------------------------------------------------------
# Estado e detecção
# --------------------------------------------------------------------------

def apply_sync(state, sig, today):
    """Atualiza o estado e devolve os artistas novos a avisar.

    Na primeira execução (linha de base) nada é avisado.
    """
    known = state.setdefault("artists", {})
    pending = state.setdefault("pending", {})
    today_s = today.isoformat()
    new = []

    cutoff = (today - dt.timedelta(days=PENDING_DAYS)).isoformat()
    for key in list(pending):
        pending[key]["plays"] = {ts: d for ts, d in pending[key]["plays"].items() if d >= cutoff}
        if not pending[key]["plays"]:
            del pending[key]

    for key, a in sig.artists.items():
        if key in known:
            known[key]["ids"] = sorted(set(known[key]["ids"]) | a["ids"])
            continue
        p = pending.setdefault(key, {"name": a["name"], "plays": {}})
        for ts in a["plays"]:
            p["plays"].setdefault(ts, today_s)
        if a["reasons"] or len(p["plays"]) >= MIN_PLAYS:
            reasons = sorted(a["reasons"]) or [f"{len(p['plays'])} reproduções"]
            known[key] = {"name": a["name"], "ids": sorted(a["ids"]), "reasons": reasons,
                          "first_seen": today_s, "muted": False}
            pending.pop(key, None)
            new.append(known[key])

    first_run = not state.get("baseline_done")
    state["baseline_done"] = True
    return [] if first_run else new


def set_muted(state, name, muted):
    a = state.get("artists", {}).get(norm(name))
    if not a:
        return False
    a["muted"] = muted
    return True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Detecta artistas novos na sua escuta.")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("spotify-auth", help="faz o login no Spotify")
    p.add_argument("--client-id", default=os.environ.get("SPOTIFY_CLIENT_ID"))
    p.add_argument("--port", type=int, default=8888)

    p = sub.add_parser("sync", help="busca artistas novos")
    p.add_argument("--source", choices=["spotify", "listenbrainz"],
                   default=os.environ.get("ACHASHOW_SOURCE", "spotify"))
    p.add_argument("--client-id", default=os.environ.get("SPOTIFY_CLIENT_ID"))
    p.add_argument("--lb-user", default=os.environ.get("LISTENBRAINZ_USER"))

    sub.add_parser("list", help="lista os artistas conhecidos")
    for cmd in ("mute", "unmute"):
        p = sub.add_parser(cmd, help=f"{cmd} um artista")
        p.add_argument("name")

    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    state_path = data_dir / "artists.json"
    state = load_json(state_path, {})
    http = Http()

    if args.cmd == "spotify-auth":
        if not args.client_id:
            ap.error("informe --client-id ou a variável SPOTIFY_CLIENT_ID")
        spotify_login(Spotify(args.client_id, http, data_dir / "spotify_token.json"), port=args.port)
        print("Login do Spotify salvo.")
        return 0

    if args.cmd == "sync":
        if args.source == "spotify":
            if not args.client_id:
                ap.error("informe --client-id ou a variável SPOTIFY_CLIENT_ID")
            sp = Spotify(args.client_id, http, data_dir / "spotify_token.json")
            try:
                sig = spotify_signals(sp)
            except ReauthRequired as e:
                print(f"ERRO: {e}", file=sys.stderr)
                return 2
            days = sp.days_until_reauth()
            if days is not None and days <= REAUTH_WARN_DAYS:
                print(f"AVISO: o login do Spotify expira em {max(days, 0):.0f} dias; "
                      "rode `spotify-auth` de novo.", file=sys.stderr)
        else:
            if not args.lb_user:
                ap.error("informe --lb-user ou a variável LISTENBRAINZ_USER")
            sig = listenbrainz_signals(args.lb_user, http)

        first_run = not state.get("baseline_done")
        new = apply_sync(state, sig, dt.date.today())
        save_json(state_path, state)
        if first_run:
            print(f"Linha de base criada com {len(state['artists'])} artistas.")
        elif new:
            print(f"{len(new)} artista(s) novo(s):")
            for a in new:
                print(f"  - {a['name']} ({', '.join(a['reasons'])})")
        else:
            print("Nenhum artista novo.")
        return 0

    if args.cmd == "list":
        for a in sorted(state.get("artists", {}).values(), key=lambda a: norm(a["name"])):
            print(f"{a['name']}{'  [mudo]' if a['muted'] else ''}")
        return 0

    if args.cmd in ("mute", "unmute"):
        if not set_muted(state, args.name, args.cmd == "mute"):
            print(f"Artista não encontrado: {args.name}", file=sys.stderr)
            return 1
        save_json(state_path, state)
        return 0


if __name__ == "__main__":
    sys.exit(main())
