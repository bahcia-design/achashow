import datetime as dt
import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import artist_sync as a
from jambase import JamBase, summarize


class FakeHttp:
    """Responde por (método, URL sem query); registra as chamadas."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, params=None, headers=None, data=None):
        self.calls.append((method, url, params, headers, data))
        handler = self.routes[(method, url)]
        result = handler(params or {}, headers or {}, data or {})
        if isinstance(result, a.HttpError):
            raise result
        return result


def run_server(handler_cls):
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class TmpDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------

class PkceTest(unittest.TestCase):
    def test_vetor_do_rfc7636(self):
        self.assertEqual(a.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
                         "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")


class NormTest(unittest.TestCase):
    def test_ignora_caixa_espacos_e_unicode(self):
        self.assertEqual(a.norm("  Mass  of the FERMENTING Dregs "), "mass of the fermenting dregs")
        self.assertEqual(a.norm("Ｔｏｅ"), "toe")


class HttpRetryTest(unittest.TestCase):
    def test_tenta_de_novo_em_429_respeitando_retry_after(self):
        hits = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.headers["User-Agent"])
                if len(hits) < 3:
                    self.send_response(429)
                    self.send_header("Retry-After", "7")
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, *args):
                pass

        server = run_server(H)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        sleeps = []
        http = a.Http(sleep=sleeps.append)
        status, body = http.request("GET", f"http://127.0.0.1:{server.server_address[1]}/x")
        self.assertEqual((status, body), (200, {"ok": True}))
        self.assertEqual(sleeps, [7.0, 7.0])
        self.assertEqual(hits[0], a.USER_AGENT)

    def test_desiste_depois_do_limite(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(429)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = run_server(H)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        sleeps = []
        http = a.Http(sleep=sleeps.append, max_retries=2)
        with self.assertRaises(a.HttpError) as ctx:
            http.request("GET", f"http://127.0.0.1:{server.server_address[1]}/x")
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(sleeps, [1, 2])   # sem Retry-After: espera exponencial


# ---------------------------------------------------------------------------

def token_ok(access="novo", refresh=None, expires_in=3600):
    body = {"access_token": access, "expires_in": expires_in}
    if refresh:
        body["refresh_token"] = refresh
    return lambda p, h, d: (200, body)


class SpotifyTokenTest(TmpDirTest):
    def make(self, routes, now, token=None):
        path = self.dir / "tok.json"
        if token:
            path.write_text(json.dumps(token))
        return a.Spotify("cid", FakeHttp(routes), path, now=lambda: now[0])

    def test_renova_token_vencido_e_mantem_data_da_autorizacao(self):
        now = [1_000_000.0]
        routes = {("POST", a.SPOTIFY_TOKEN_URL): token_ok("novo", refresh="rt2"),
                  ("GET", a.SPOTIFY_API + "/me/x"): lambda p, h, d: (200, {"auth": h["Authorization"]})}
        sp = self.make(routes, now, {"access_token": "velho", "refresh_token": "rt1",
                                     "expires_at": now[0] - 1, "authorized_at": 500.0})
        self.assertEqual(sp.get("/me/x"), {"auth": "Bearer novo"})
        saved = json.loads((self.dir / "tok.json").read_text())
        self.assertEqual(saved["refresh_token"], "rt2")
        self.assertEqual(saved["authorized_at"], 500.0)

    def test_renova_em_401_e_repete_a_chamada(self):
        now = [1000.0]
        calls = []

        def api(p, h, d):
            calls.append(h["Authorization"])
            return a.HttpError(401, {}) if len(calls) == 1 else (200, {"ok": 1})

        routes = {("POST", a.SPOTIFY_TOKEN_URL): token_ok("novo"),
                  ("GET", a.SPOTIFY_API + "/me/x"): api}
        sp = self.make(routes, now, {"access_token": "velho", "refresh_token": "rt",
                                     "expires_at": 99999, "authorized_at": 0})
        self.assertEqual(sp.get("/me/x"), {"ok": 1})
        self.assertEqual(calls, ["Bearer velho", "Bearer novo"])

    def test_refresh_token_morto_pede_novo_login(self):
        routes = {("POST", a.SPOTIFY_TOKEN_URL):
                  lambda p, h, d: a.HttpError(400, {"error": "invalid_grant"})}
        sp = self.make(routes, [1000.0], {"access_token": "x", "refresh_token": "rt",
                                          "expires_at": 0, "authorized_at": 0})
        with self.assertRaises(a.ReauthRequired):
            sp.get("/me/x")

    def test_sem_login_pede_login(self):
        with self.assertRaises(a.ReauthRequired):
            self.make({}, [0]).get("/me/x")

    def test_dias_ate_reautorizar(self):
        now = [100 * 86400.0]
        sp = self.make({}, now, {"access_token": "x", "authorized_at": 0.0})
        self.assertAlmostEqual(sp.days_until_reauth(), a.REFRESH_TTL_DAYS - 100)


class SpotifyLoginTest(TmpDirTest):
    def test_fluxo_completo_com_callback_local(self):
        exchanged = {}

        def token(p, h, d):
            exchanged.update(d)
            return 200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

        sp = a.Spotify("cid", FakeHttp({("POST", a.SPOTIFY_TOKEN_URL): token}),
                       self.dir / "tok.json", now=lambda: 1234.0)

        def fake_browser(url):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            self.assertEqual(q["code_challenge_method"], "S256")
            self.assertEqual(q["scope"], a.SPOTIFY_SCOPES)
            fake_browser.challenge = q["code_challenge"]
            cb = f"{q['redirect_uri']}?code=CODE&state={q['state']}"
            threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=5).read(), daemon=True).start()

        a.spotify_login(sp, port=0, open_browser=fake_browser, timeout=10)
        self.assertEqual(exchanged["code"], "CODE")
        self.assertTrue(exchanged["redirect_uri"].startswith("http://127.0.0.1:"))
        self.assertEqual(a.pkce_challenge(exchanged["code_verifier"]), fake_browser.challenge)
        saved = json.loads((self.dir / "tok.json").read_text())
        self.assertEqual((saved["refresh_token"], saved["authorized_at"]), ("rt", 1234.0))

    def test_state_errado_e_recusado(self):
        sp = a.Spotify("cid", FakeHttp({}), self.dir / "tok.json")

        def fake_browser(url):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            cb = f"{q['redirect_uri']}?code=CODE&state=OUTRO"
            threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=5).read(), daemon=True).start()

        with self.assertRaisesRegex(RuntimeError, "state"):
            a.spotify_login(sp, port=0, open_browser=fake_browser, timeout=10)


# ---------------------------------------------------------------------------

class StubSpotify:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        return self.pages(path, params or {})


class SpotifySignalsTest(unittest.TestCase):
    def test_top_seguidos_paginados_e_recentes(self):
        def pages(path, params):
            if path == "/me/top/artists":
                return {"items": [{"name": "toe", "id": "t1"}]} if params["time_range"] == "short_term" else {"items": []}
            if path == "/me/following":
                if "after" not in params:
                    return {"artists": {"items": [{"name": "Coldplay", "id": "c1"}],
                                        "cursors": {"after": "c1"}, "next": "http://next"}}
                return {"artists": {"items": [{"name": "MOFD", "id": "m1"}], "cursors": {"after": None}, "next": None}}
            if path == "/me/player/recently-played":
                return {"items": [{"played_at": "t1", "track": {"artists": [{"name": "Lume", "id": "l1"}]}},
                                  {"played_at": "t2", "track": {"artists": [{"name": "Lume", "id": "l1"}]}}]}

        stub = StubSpotify(pages)
        sig = a.spotify_signals(stub)
        self.assertEqual(sig.artists["toe"]["reasons"], {"top:short_term"})
        self.assertEqual(sig.artists["mofd"]["reasons"], {"segue"})
        self.assertEqual(sig.artists["lume"]["plays"], {"t1", "t2"})
        following = [p for path, p in stub.calls if path == "/me/following"]
        self.assertEqual([p.get("after") for p in following], [None, "c1"])


class ListenBrainzSignalsTest(unittest.TestCase):
    def test_estatisticas_e_listens(self):
        base = a.LISTENBRAINZ_API
        routes = {
            ("GET", f"{base}/stats/user/fer%20p/artists"): lambda p, h, d: (
                (204, None) if p["range"] == "all_time" else
                (200, {"payload": {"artists": [{"artist_name": "toe", "artist_mbid": "abc"},
                                               {"artist_name": "Lume", "artist_mbids": []}]}})),
            ("GET", f"{base}/user/fer%20p/listens"): lambda p, h, d: (200, {"payload": {"listens": [
                {"listened_at": 1, "track_metadata": {"artist_name": "Novo"}},
                {"listened_at": 2, "track_metadata": {"artist_name": "Novo"}}]}}),
        }
        sig = a.listenbrainz_signals("fer p", FakeHttp(routes))
        self.assertEqual(sig.artists["toe"]["ids"], {"mbid:abc"})
        self.assertEqual(sig.artists["toe"]["reasons"], {"top:month", "top:half_yearly"})
        self.assertEqual(sig.artists["lume"]["ids"], set())
        self.assertEqual(sig.artists["novo"]["plays"], {"1", "2"})


# ---------------------------------------------------------------------------

def signals(*entries):
    sig = a.Signals()
    for name, reason, plays in entries:
        if reason:
            sig.add(name, f"id:{name}", reason)
        for ts in plays:
            sig.play(name, f"id:{name}", ts)
    return sig


class ApplySyncTest(unittest.TestCase):
    D0 = dt.date(2026, 9, 1)

    def test_primeira_execucao_e_silenciosa(self):
        state = {}
        new = a.apply_sync(state, signals(("toe", "segue", []), ("Coldplay", "top:long_term", [])), self.D0)
        self.assertEqual(new, [])
        self.assertEqual(set(state["artists"]), {"toe", "coldplay"})

    def test_avisa_artista_novo_uma_vez_so(self):
        state = {}
        a.apply_sync(state, signals(("toe", "segue", [])), self.D0)
        new = a.apply_sync(state, signals(("toe", "segue", []), ("MOFD", "top:short_term", [])), self.D0)
        self.assertEqual([x["name"] for x in new], ["MOFD"])
        self.assertEqual(a.apply_sync(state, signals(("MOFD", "top:short_term", [])), self.D0), [])

    def test_uma_reproducao_so_nao_conta(self):
        state = {}
        a.apply_sync(state, signals(), self.D0)
        self.assertEqual(a.apply_sync(state, signals(("Playlist", None, ["t1"])), self.D0), [])
        self.assertNotIn("playlist", state["artists"])

    def test_reproducoes_somam_entre_execucoes_sem_contar_repetida(self):
        state = {}
        a.apply_sync(state, signals(), self.D0)
        a.apply_sync(state, signals(("Lume", None, ["t1"])), self.D0)
        self.assertEqual(a.apply_sync(state, signals(("Lume", None, ["t1"])), self.D0), [])
        new = a.apply_sync(state, signals(("Lume", None, ["t1", "t2"])), self.D0)
        self.assertEqual(new[0]["reasons"], ["2 reproduções"])
        self.assertNotIn("lume", state["pending"])

    def test_reproducao_antiga_e_esquecida(self):
        state = {}
        a.apply_sync(state, signals(), self.D0)
        a.apply_sync(state, signals(("Lume", None, ["t1"])), self.D0)
        later = self.D0 + dt.timedelta(days=a.PENDING_DAYS + 1)
        self.assertEqual(a.apply_sync(state, signals(("Lume", None, ["t2"])), later), [])
        self.assertEqual(list(state["pending"]["lume"]["plays"]), ["t2"])

    def test_mute_e_unmute(self):
        state = {}
        a.apply_sync(state, signals(("toe", "segue", [])), self.D0)
        self.assertTrue(a.set_muted(state, "TOE", True))
        self.assertTrue(state["artists"]["toe"]["muted"])
        self.assertFalse(a.set_muted(state, "inexistente", True))


class CliTest(TmpDirTest):
    def test_list_mute_e_artista_inexistente(self):
        state = {"baseline_done": True, "artists": {"toe": {"name": "toe", "ids": [], "reasons": [],
                                                            "first_seen": "2026-09-01", "muted": False}}}
        (self.dir / "artists.json").write_text(json.dumps(state))
        self.assertEqual(a.main(["--state-dir", str(self.dir), "mute", "toe"]), 0)
        saved = json.loads((self.dir / "artists.json").read_text())
        self.assertTrue(saved["artists"]["toe"]["muted"])
        self.assertEqual(a.main(["--state-dir", str(self.dir), "unmute", "nada"]), 1)


# ---------------------------------------------------------------------------

class JamBaseTest(unittest.TestCase):
    def test_nome_exato_e_paginacao_por_artist_id(self):
        base = "https://api.data.jambase.com/v3"
        pages = {1: {"events": [{"name": "e1"}], "pagination": {"nextPage": "x"}},
                 2: {"events": [{"name": "e2"}], "pagination": {"nextPage": None}}}
        routes = {
            ("GET", f"{base}/artists"): lambda p, h, d: (200, {"artists": [
                {"name": "toe", "identifier": "jambase:51211"}, {"name": "Toé", "identifier": "jambase:2"},
                {"name": "Lil Toe", "identifier": "jambase:3"}]}),
            ("GET", f"{base}/events"): lambda p, h, d: (200, pages[p["page"]]),
        }
        http = FakeHttp(routes)
        jb = JamBase("KEY", http)
        self.assertEqual([x["identifier"] for x in jb.find_artists("TOE")], ["jambase:51211"])
        self.assertEqual([e["name"] for e in jb.events(["jambase:51211", "jambase:9"])], ["e1", "e2"])
        _, _, params, headers, _ = http.calls[-1]
        self.assertEqual(params["artistId"], "jambase:51211|jambase:9")
        self.assertEqual(params["geoCountryIso2"], "BR")
        self.assertEqual(headers["Authorization"], "Bearer KEY")

    def test_resumo_do_evento(self):
        e = {"name": "toe at Cine Joia", "startDate": "2026-09-18T20:00:00", "url": "u",
             "location": {"name": "Cine Joia", "address": {"addressLocality": "São Paulo"}}}
        self.assertEqual(summarize(e), {"date": "2026-09-18", "name": "toe at Cine Joia",
                                        "venue": "Cine Joia", "city": "São Paulo", "url": "u"})


if __name__ == "__main__":
    unittest.main()
