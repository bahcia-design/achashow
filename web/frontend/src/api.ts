// Tipos e chamadas do backend (web/api.py).

export type Overview = {
  artists: number
  muted: number
  shows_last_run: string | null
  news_last_run: string | null
  jambase_calls: number
  jambase_cap: number
  spotify_reauth_days: number | null
  seen_until: string
}

export type Show = {
  id: string
  date: string
  name: string
  venue: string
  city: string
  url: string
  artist: string
  artist_key: string
  first_seen: string
  is_new: boolean
}

export type NewsItem = { title: string; link: string; source: string; date: string; first_seen: string }
export type NewsGroup = { artist: string; artist_key: string; items: NewsItem[]; latest: string; is_new: boolean }

export type Artist = {
  key: string
  name: string
  reasons: string[]
  first_seen: string
  muted: boolean
  shows: number
  news: number
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

export const api = {
  overview: () => call<Overview>('/overview'),
  shows: () => call<Show[]>('/shows'),
  news: () => call<NewsGroup[]>('/news'),
  artists: () => call<Artist[]>('/artists'),
  sync: () => call<Overview & { ok: boolean; error: string | null }>('/sync', { method: 'POST' }),
  seen: () => call<{ seen_until: string }>('/seen', { method: 'POST' }),
  mute: (key: string, muted: boolean) =>
    call<{ synced: boolean }>(`/artists/${encodeURIComponent(key)}/mute`, {
      method: 'POST',
      body: JSON.stringify({ muted }),
    }),
}

// ---- formatação ----

const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const WEEKDAYS = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb']

export function parts(iso: string) {
  const [y, m, d] = iso.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  return { day: String(d).padStart(2, '0'), month: MONTHS[m - 1], weekday: WEEKDAYS[date.getDay()], year: y }
}

export function monthLabel(iso: string) {
  const { year } = parts(iso)
  const full = new Date(iso + 'T12:00:00').toLocaleDateString('pt-BR', { month: 'long' })
  return year === new Date().getFullYear() ? full : `${full} ${year}`
}

export function daysUntil(iso: string) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((new Date(iso + 'T00:00:00').getTime() - today.getTime()) / 86400000)
}

export function relativeDay(iso: string | null) {
  if (!iso) return 'nunca'
  const n = -daysUntil(iso)
  if (n <= 0) return 'hoje'
  if (n === 1) return 'ontem'
  return `há ${n} dias`
}

export function reasonLabel(reasons: string[]) {
  const map: Record<string, string> = {
    segue: 'você segue',
    'top:short_term': 'top do mês',
    'top:medium_term': 'top do semestre',
    'top:long_term': 'top de sempre',
    'top:month': 'top do mês',
    'top:half_yearly': 'top do semestre',
    'top:all_time': 'top de sempre',
  }
  return reasons.map((r) => map[r] ?? r)
}
