import { useMemo, useState } from 'react'
import { reasonLabel, type Artist } from '../api'
import { Empty } from './Empty'

type Filter = 'all' | 'active' | 'muted'

export function ArtistsView({ artists, onToggle }: { artists: Artist[]; onToggle: (key: string, muted: boolean) => void }) {
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<Filter>('all')

  const list = useMemo(() => {
    const term = q.trim().toLowerCase()
    return artists.filter(
      (a) =>
        (!term || a.name.toLowerCase().includes(term)) &&
        (filter === 'all' || (filter === 'muted' ? a.muted : !a.muted)),
    )
  }, [artists, q, filter])

  const muted = artists.filter((a) => a.muted).length
  const filters: { id: Filter; label: string }[] = [
    { id: 'all', label: `todos ${artists.length}` },
    { id: 'active', label: `acompanhando ${artists.length - muted}` },
    { id: 'muted', label: `silenciados ${muted}` },
  ]

  return (
    <div>
      <p className="mb-5 max-w-xl text-sm text-mute">
        Estes artistas entram sozinhos, a partir do que você ouve no Spotify. Silencie quem você não quer acompanhar: a busca para
        de procurar shows dele.
      </p>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="buscar artista"
          className="w-full rounded-full border border-line bg-panel px-5 py-2.5 text-sm outline-none transition placeholder:text-mute focus:border-heat sm:max-w-xs"
        />
        <div className="flex gap-1 overflow-x-auto">
          {filters.map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`shrink-0 rounded-full px-3.5 py-1.5 font-mono text-xs transition ${
                filter === f.id ? 'bg-paper text-ink' : 'text-mute hover:text-paper'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {!list.length ? (
        <Empty title="Ninguém por aqui" />
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-panel">
          {list.map((a) => (
            <li key={a.key} className={`flex items-center justify-between gap-4 px-5 py-3.5 transition ${a.muted ? 'opacity-45' : ''}`}>
              <div className="min-w-0">
                <p className="truncate font-semibold">{a.name}</p>
                <p className="truncate font-mono text-[11px] text-mute">
                  {reasonLabel(a.reasons).join(' · ')}
                  {a.shows > 0 && <span className="text-heat"> · {a.shows} {a.shows === 1 ? 'show' : 'shows'}</span>}
                  {a.news > 0 && <span className="text-cool"> · {a.news} {a.news === 1 ? 'notícia' : 'notícias'}</span>}
                </p>
              </div>
              <button
                onClick={() => onToggle(a.key, !a.muted)}
                className={`shrink-0 rounded-full border px-3.5 py-1.5 text-xs font-medium transition ${
                  a.muted ? 'border-line text-mute hover:border-paper hover:text-paper' : 'border-line text-paper hover:border-heat hover:text-heat'
                }`}
              >
                {a.muted ? 'voltar a acompanhar' : 'silenciar'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
