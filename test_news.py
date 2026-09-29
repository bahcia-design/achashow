import datetime as dt
import unittest

from news import check_news, parse_rss, relevant

D0 = dt.date(2026, 9, 29)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>toe anuncia show único no Brasil em 2026 - Tenho Mais Discos Que Amigos</title>
  <link>https://n/1</link><pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate><source>TMDQA</source></item>
<item><title>Kotoe lança disco novo e anuncia turnê no Brasil - Site</title>
  <link>https://n/2</link><pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>toe fala sobre o novo disco - Site</title>
  <link>https://n/3</link><pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>toe anuncia show em São Paulo - Site</title>
  <link>https://n/4</link><pubDate>Fri, 01 May 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class FakeHttp:
    def __init__(self, body):
        self.body = body
        self.queries = []

    def request(self, method, url, params=None, headers=None, data=None):
        self.queries.append(params["q"])
        return 200, self.body


def artist(name, muted=False):
    return {"name": name, "muted": muted}


class NewsTest(unittest.TestCase):
    def test_parse_rss(self):
        items = parse_rss(RSS)
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0]["date"], "2026-09-21")
        self.assertEqual(items[0]["source"], "TMDQA")
        self.assertEqual(items[0]["title"], "toe anuncia show único no Brasil em 2026")   # sem " - Site"

    def test_relevante_exige_nome_exato_e_palavra_de_anuncio(self):
        self.assertTrue(relevant("toe anuncia show único no Brasil", "toe"))
        self.assertTrue(relevant("TOE anuncia show extra em São Paulo", "toe"))
        self.assertFalse(relevant("Ed Sheeran sobre saída da turnê no Brasil: Sei quem sou", "Sou"))
        self.assertFalse(relevant("Interpol e Queens of the Stone Age anunciam show na Cidade do México",
                                  "Queens of the Stone Age"))   # fora do Brasil
        self.assertTrue(relevant("American Football retorna ao Brasil para show único", "American Football"))
        self.assertFalse(relevant("Kotoe anuncia turnê no Brasil", "toe"))          # nome dentro de outra palavra
        self.assertFalse(relevant("toe fala sobre o novo disco", "toe"))  # sem anúncio
        self.assertFalse(relevant("Stray Kids promete show intenso no Rock in Rio", "Stray Kids"))
        self.assertFalse(relevant("TCU cobra governo sobre Angra 3 e critica festival de horrores", "ANGRA"))
        self.assertTrue(relevant("Mass of the Fermenting Dregs estreia em São Paulo em 2027",
                                 "MASS OF THE FERMENTING DREGS"))

    def test_um_aviso_por_artista_e_so_de_novo_depois_do_intervalo(self):
        more = RSS.replace("https://n/1", "https://n/5").replace("Tenho Mais Discos Que Amigos", "Billboard")
        state = {"artists": {"toe": artist("toe")}}
        news = {}
        alerts = check_news(state, news, FakeHttp(RSS.replace("</channel>", more[more.index("<item>"):more.index("</item>") + 7] + "</channel>")),
                            D0, sleep=lambda s: None)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["count"], 2)
        later = RSS.replace("https://n/1", "https://n/9").replace("21 Sep", "05 Oct")
        self.assertEqual(check_news(state, news, FakeHttp(later), D0 + dt.timedelta(days=7), sleep=lambda s: None), [])
        later2 = RSS.replace("https://n/1", "https://n/10").replace("21 Sep", "20 Oct")
        self.assertEqual(len(check_news(state, news, FakeHttp(later2), D0 + dt.timedelta(days=22), sleep=lambda s: None)), 1)

    def test_so_avisa_noticia_recente_relevante_uma_vez(self):
        state = {"artists": {"toe": artist("toe")}}
        news = {}
        http = FakeHttp(RSS)
        new = check_news(state, news, http, D0, sleep=lambda s: None)
        self.assertEqual([n["link"] for n in new], ["https://n/1"])   # n/4 é velha demais
        self.assertEqual(new[0]["artist"], "toe")
        self.assertEqual(check_news(state, news, http, D0, sleep=lambda s: None), [])

    def test_ignora_silenciados_e_pausa_entre_buscas(self):
        state = {"artists": {"a": artist("A"), "b": artist("B"), "c": artist("C", muted=True)}}
        pauses = []
        http = FakeHttp(RSS)
        check_news(state, {}, http, D0, sleep=pauses.append)
        self.assertEqual(len(http.queries), 2)
        self.assertEqual(len(pauses), 1)

    def test_esquece_noticias_antigas(self):
        news = {"items": {"x": {"first_seen": "2026-01-01", "date": "2026-01-01"}}}
        check_news({"artists": {}}, news, FakeHttp(RSS), D0)
        self.assertEqual(news["items"], {})


if __name__ == "__main__":
    unittest.main()
