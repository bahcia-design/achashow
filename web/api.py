"""API do front do achashow.

Lê o que a rotina diária do GitHub grava em state/ (faz `git pull` antes)
e, quando um artista é silenciado, grava de volta e faz `git push`, para
a rotina parar de buscar shows dele.

Rodar:  .venv\\Scripts\\python -m uvicorn web.api:app --port 8000
"""

import datetime as dt
import json
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from artist_sync import DATA_DIR, REFRESH_TTL_DAYS, STATE_DIR, load_json, norm, save_json  # noqa: E402
from shows import MONTHLY_CAP  # noqa: E402

UI_PATH = DATA_DIR / "ui.json"          # só deste PC: até quando já vi os avisos
DIST = ROOT / "web" / "frontend" / "dist"
_git_lock = threading.Lock()

app = FastAPI(title="achashow")


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60)


def pull():
    """Traz o que a rotina diária gravou. Devolve o erro, se houver."""
    with _git_lock:
        r = _git("pull", "--ff-only", "-q")
        return None if r.returncode == 0 else (r.stderr.strip() or r.stdout.strip())


def commit_state(message, change):
    """Aplica `change()` em state/, faz commit e push; tenta de novo se a rotina gravou antes."""
    with _git_lock:
        for _ in range(3):
            _git("pull", "--ff-only", "-q")
            change()
            _git("add", "state")
            if _git("diff", "--cached", "--quiet").returncode == 0:
                return True
            _git("commit", "-q", "-m", message)
            if _git("push", "-q").returncode == 0:
                return True
            # Alguém (a rotina) gravou antes: desfaz só o nosso commit e tenta de novo.
            _git("reset", "-q", "--soft", "HEAD~1")
            _git("restore", "--staged", "--worktree", "state")
        return False


# --------------------------------------------------------------------------
# leitura
# --------------------------------------------------------------------------

def _state():
    return (load_json(STATE_DIR / "artists.json", {}),
            load_json(STATE_DIR / "shows.json", {}),
            load_json(STATE_DIR / "news.json", {}))


def _seen_until():
    return load_json(UI_PATH, {}).get("seen_until", "")


def _muted(artists):
    return {k for k, a in artists.get("artists", {}).items() if a.get("muted")}


@app.get("/api/overview")
def overview():
    artists, shows, news = _state()
    month = dt.date.today().isoformat()[:7]
    token = load_json(DATA_DIR / "spotify_token.json", {})
    reauth = None
    if token.get("authorized_at"):
        expires = dt.datetime.fromtimestamp(token["authorized_at"]) + dt.timedelta(days=REFRESH_TTL_DAYS)
        reauth = (expires.date() - dt.date.today()).days
    return {
        "artists": len(artists.get("artists", {})),
        "muted": len(_muted(artists)),
        "shows_last_run": shows.get("last_run"),
        "news_last_run": news.get("last_run"),
        "jambase_calls": shows.get("usage", {}).get(month, 0),
        "jambase_cap": MONTHLY_CAP,
        "spotify_reauth_days": reauth,
        "seen_until": _seen_until(),
    }


@app.get("/api/shows")
def list_shows():
    artists, shows, _ = _state()
    muted, seen = _muted(artists), _seen_until()
    out = [{**e, "id": eid, "is_new": e.get("first_seen", "") > seen}
           for eid, e in shows.get("events", {}).items()
           if e.get("artist_key") not in muted and e.get("status") != "cancelled"]
    return sorted(out, key=lambda e: (e["date"], e["artist"]))


@app.get("/api/news")
def list_news():
    """Notícias agrupadas por artista, do grupo mais recente para o mais antigo."""
    artists, _, news = _state()
    muted, seen = _muted(artists), _seen_until()
    groups = {}
    for n in news.get("items", {}).values():
        key = norm(n["artist"])
        if key in muted:
            continue
        g = groups.setdefault(key, {"artist": n["artist"], "artist_key": key, "items": []})
        g["items"].append(n)
    out = []
    for g in groups.values():
        g["items"].sort(key=lambda n: n["date"], reverse=True)
        g["latest"] = g["items"][0]["date"]
        g["is_new"] = any(n.get("first_seen", "") > seen for n in g["items"])
        out.append(g)
    return sorted(out, key=lambda g: g["latest"], reverse=True)


@app.get("/api/artists")
def list_artists():
    artists, shows, news = _state()
    show_count, news_count = {}, {}
    for e in shows.get("events", {}).values():
        show_count[e.get("artist_key")] = show_count.get(e.get("artist_key"), 0) + 1
    for n in news.get("items", {}).values():
        news_count[norm(n["artist"])] = news_count.get(norm(n["artist"]), 0) + 1
    out = [{"key": k, "name": a["name"], "reasons": a.get("reasons", []), "first_seen": a.get("first_seen"),
            "muted": a.get("muted", False), "shows": show_count.get(k, 0), "news": news_count.get(k, 0)}
           for k, a in artists.get("artists", {}).items()]
    return sorted(out, key=lambda a: norm(a["name"]))


# --------------------------------------------------------------------------
# ações
# --------------------------------------------------------------------------

class MuteBody(BaseModel):
    muted: bool


@app.post("/api/artists/{key}/mute")
def mute(key: str, body: MuteBody):
    path = STATE_DIR / "artists.json"
    if key not in load_json(path, {}).get("artists", {}):
        raise HTTPException(404, "artista não encontrado")

    def change():
        state = load_json(path, {})
        if key in state.get("artists", {}):
            state["artists"][key]["muted"] = body.muted
            save_json(path, state)

    name = load_json(path, {})["artists"][key]["name"]
    verb = "Silencia" if body.muted else "Volta a acompanhar"
    synced = commit_state(f"{verb} {name}", change)
    return {"key": key, "muted": body.muted, "synced": synced}


@app.post("/api/sync")
def sync():
    error = pull()
    return {"ok": error is None, "error": error, **overview()}


@app.post("/api/seen")
def mark_seen():
    ui = load_json(UI_PATH, {})
    ui["seen_until"] = dt.date.today().isoformat()
    save_json(UI_PATH, ui)
    return ui


# --------------------------------------------------------------------------
# front já compilado (npm run build)
# --------------------------------------------------------------------------

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = DIST / path
        return FileResponse(file if path and file.is_file() else DIST / "index.html")
