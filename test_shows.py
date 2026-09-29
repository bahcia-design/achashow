import datetime as dt
import unittest

from shows import check_shows

D0 = dt.date(2026, 10, 1)


def artist(name, muted=False):
    return {"name": name, "ids": [], "reasons": ["segue"], "first_seen": "2026-09-29", "muted": muted}


def event(eid, date, venue="Cine Joia"):
    return {"identifier": eid, "name": f"show {eid}", "startDate": f"{date}T20:00:00", "url": f"u/{eid}",
            "eventStatus": "scheduled",
            "location": {"name": venue, "address": {"addressLocality": "São Paulo"}}}


class StubJamBase:
    """`catalog`: nome -> (ids, shows futuros no mundo); `by_id`: id -> eventos no país."""

    def __init__(self, catalog, by_id):
        self.catalog = catalog
        self.by_id = by_id
        self.calls = []

    def find_artists(self, name):
        self.calls.append(("artists", name))
        ids, upcoming = self.catalog.get(name, ([], 0))
        return [{"identifier": i, "x-numUpcomingEvents": upcoming} for i in ids]

    def events(self, ids, country="BR", past=False, max_pages=5):
        self.calls.append(("events", tuple(ids), country))
        return [e for i in ids for e in self.by_id.get(i, [])]


class CheckShowsTest(unittest.TestCase):
    def setUp(self):
        self.state = {"artists": {"toe": artist("toe"), "mofd": artist("MOFD"), "cold": artist("Coldplay")}}
        self.jb = StubJamBase(
            catalog={"toe": (["jb:1"], 2), "MOFD": (["jb:2"], 5), "Coldplay": (["jb:3"], 0)},
            by_id={"jb:1": [event("e1", "2026-11-10")], "jb:2": []},
        )

    def test_primeira_checagem_resolve_ids_e_acha_show(self):
        shows = {}
        new, used = check_shows(self.state, shows, self.jb, D0)
        self.assertEqual([e["artist"] for e in new], ["toe"])
        self.assertEqual(new[0]["city"], "São Paulo")
        # Coldplay sem show futuro no mundo: 1 chamada só. toe e MOFD: 2 cada.
        self.assertEqual(used, 5)
        self.assertEqual(shows["usage"]["2026-10"], 5)
        self.assertNotIn(("events", ("jb:3",), "BR"), self.jb.calls)

    def test_show_ja_visto_nao_e_novo_de_novo(self):
        shows = {}
        check_shows(self.state, shows, self.jb, D0)
        new, used = check_shows(self.state, shows, self.jb, D0 + dt.timedelta(days=1))
        self.assertEqual(new, [])
        # IDs já guardados: só a chamada de eventos (Coldplay também, agora que tem ID).
        self.assertEqual(used, 3)
        self.assertEqual(shows["events"]["e1"]["first_seen"], "2026-10-01")

    def test_orcamento_prioriza_quem_esta_ha_mais_tempo_sem_checar(self):
        shows = {}
        check_shows(self.state, shows, self.jb, D0, budget=2)   # dá só para 1 artista
        first = {k for k, c in shows["checks"].items() if c.get("last_checked")}
        self.assertEqual(len(first), 1)
        check_shows(self.state, shows, self.jb, D0 + dt.timedelta(days=1), budget=2)
        second = {k for k, c in shows["checks"].items() if c.get("last_checked") == "2026-10-02"}
        self.assertTrue(second and not (second & first))

    def test_respeita_teto_mensal(self):
        shows = {"usage": {"2026-10": 999}}
        new, used = check_shows(self.state, shows, self.jb, D0, budget=30)
        # Sobra 1 chamada, mas artista novo precisa de 2 (ID + eventos): não gasta nada.
        self.assertEqual(used, 0)
        self.assertEqual(shows["usage"]["2026-10"], 999)
        shows["usage"]["2026-10"] = 998
        _, used = check_shows(self.state, shows, self.jb, D0, budget=30)
        # Coldplay ("cold") vem primeiro e custa 1 (sem show futuro); o próximo precisaria de 2.
        self.assertEqual(used, 1)
        self.assertEqual(shows["usage"]["2026-10"], 999)

    def test_ignora_silenciados(self):
        self.state["artists"]["toe"]["muted"] = True
        new, _ = check_shows(self.state, {}, self.jb, D0)
        self.assertEqual(new, [])
        self.assertNotIn(("artists", "toe"), self.jb.calls)

    def test_artista_fora_da_jambase_so_e_procurado_de_novo_depois_de_30_dias(self):
        self.state = {"artists": {"x": artist("Banda Minúscula")}}
        shows = {}
        _, used = check_shows(self.state, shows, self.jb, D0)
        self.assertEqual(used, 1)
        _, used = check_shows(self.state, shows, self.jb, D0 + dt.timedelta(days=10))
        self.assertEqual(used, 0)
        _, used = check_shows(self.state, shows, self.jb, D0 + dt.timedelta(days=31))
        self.assertEqual(used, 1)

    def test_remove_shows_que_ja_passaram(self):
        shows = {}
        check_shows(self.state, shows, self.jb, D0)
        check_shows(self.state, shows, self.jb, dt.date(2026, 11, 11))
        self.assertNotIn("e1", shows["events"])


if __name__ == "__main__":
    unittest.main()
