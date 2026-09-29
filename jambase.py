"""Cliente mínimo da JamBase Data API (v3).

A busca por `artistName` em /events é por palavra-chave e traz falsos
positivos (ex.: "toe" casa com qualquer evento que tenha "Kotoe"). Por
isso o caminho é: achar o artista de nome exato em /artists e buscar os
eventos pelo `artistId`.
"""

import datetime as dt

from artist_sync import norm

JAMBASE_API = "https://api.data.jambase.com/v3"


class JamBase:
    def __init__(self, api_key, http):
        self.api_key = api_key
        self.http = http

    def _get(self, path, params):
        headers = {"Authorization": f"Bearer {self.api_key}"}
        return self.http.request("GET", f"{JAMBASE_API}/{path}", params=params, headers=headers)[1]

    def find_artists(self, name):
        """Artistas com o nome exato (sem diferença de caixa)."""
        data = self._get("artists", {"artistName": name, "perPage": 25})
        return [a for a in data.get("artists", []) if norm(a["name"]) == norm(name)]

    def events(self, artist_ids, country="BR", past=False, max_pages=5):
        params = {"artistId": "|".join(artist_ids), "geoCountryIso2": country, "perPage": 100}
        if past:
            params.update(expandPastEvents="true", eventDateTo=dt.date.today().isoformat(), sort="-eventDate")
        events = []
        for page in range(1, max_pages + 1):
            data = self._get("events", {**params, "page": page})
            events.extend(data.get("events", []))
            if not (data.get("pagination") or {}).get("nextPage"):
                break
        return events


def summarize(event):
    loc = event.get("location") or {}
    return {
        "date": (event.get("startDate") or "")[:10],
        "name": event.get("name", ""),
        "venue": loc.get("name", ""),
        "city": (loc.get("address") or {}).get("addressLocality", ""),
        "url": event.get("url", ""),
    }
