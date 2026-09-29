import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { api, relativeDay, type Artist, type NewsGroup, type Overview, type Show } from './api'
import { ArtistsView } from './components/ArtistsView'
import { NewsView } from './components/NewsView'
import { ShowsView } from './components/ShowsView'

type Tab = 'shows' | 'news' | 'artists'

export default function App() {
  const [tab, setTab] = useState<Tab>('shows')
  const [overview, setOverview] = useState<Overview | null>(null)
  const [shows, setShows] = useState<Show[]>([])
  const [news, setNews] = useState<NewsGroup[]>([])
  const [artists, setArtists] = useState<Artist[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const [o, s, n, a] = await Promise.all([api.overview(), api.shows(), api.news(), api.artists()])
    setOverview(o)
    setShows(s)
    setNews(n)
    setArtists(a)
  }, [])

  // Ao abrir: traz o que a rotina do GitHub gravou e carrega tudo.
  useEffect(() => {
    setBusy(true)
    api
      .sync()
      .then((r) => !r.ok && setError('Não consegui buscar as novidades do GitHub; mostrando o que já tinha aqui.'))
      .catch(() => setError('O servidor do achashow não respondeu.'))
      .finally(() => load().catch(() => {}).finally(() => setBusy(false)))
  }, [load])

  const refresh = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await api.sync()
      if (!r.ok) setError('Não consegui buscar as novidades do GitHub.')
      await load()
    } finally {
      setBusy(false)
    }
  }

  const markSeen = async () => {
    await api.seen()
    await load()
  }

  const toggleMute = async (key: string, muted: boolean) => {
    setArtists((list) => list.map((a) => (a.key === key ? { ...a, muted } : a)))
    try {
      const r = await api.mute(key, muted)
      if (!r.synced) setError('Salvei aqui, mas não consegui enviar para o GitHub. Tente atualizar depois.')
      const [s, n, o] = await Promise.all([api.shows(), api.news(), api.overview()])
      setShows(s)
      setNews(n)
      setOverview(o)
    } catch {
      setArtists((list) => list.map((a) => (a.key === key ? { ...a, muted: !muted } : a)))
      setError('Não consegui mudar esse artista.')
    }
  }

  const newShows = shows.filter((s) => s.is_new).length
  const newNews = news.filter((g) => g.is_new).length
  const hasNew = newShows + newNews > 0

  const tabs: { id: Tab; label: string; count: number; fresh: number }[] = [
    { id: 'shows', label: 'Shows', count: shows.length, fresh: newShows },
    { id: 'news', label: 'Notícias', count: news.length, fresh: newNews },
    { id: 'artists', label: 'Artistas', count: artists.length, fresh: 0 },
  ]

  return (
    <div className="relative min-h-screen overflow-x-clip">
      {/* brilho de palco */}
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[28rem] w-[60rem] -translate-x-1/2 rounded-full bg-heat/15 blur-[120px]" />

      <div className="relative mx-auto max-w-4xl px-4 pb-24 pt-10 sm:px-8 sm:pt-16">
        <header className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <motion.h1
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-5xl font-extrabold tracking-tight sm:text-7xl"
            >
              acha<span className="text-heat">show</span>
            </motion.h1>
            <p className="mt-2 text-mute">
              shows no Brasil de quem você ouve
              {overview && (
                <span className="font-mono text-xs"> · {overview.artists} artistas · última busca {relativeDay(overview.shows_last_run)}</span>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            {hasNew && (
              <button onClick={markSeen} className="rounded-full border border-line px-4 py-2 text-sm text-mute transition hover:border-paper hover:text-paper">
                marcar como visto
              </button>
            )}
            <button
              onClick={refresh}
              disabled={busy}
              className="rounded-full bg-heat px-5 py-2 text-sm font-semibold text-ink transition hover:bg-glow disabled:opacity-60"
            >
              {busy ? 'atualizando…' : 'atualizar'}
            </button>
          </div>
        </header>

        <AnimatePresence>
          {overview?.spotify_reauth_days != null && overview.spotify_reauth_days <= 30 && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-6 rounded-2xl border border-glow/40 bg-glow/10 px-5 py-3 text-sm text-glow">
              O login do Spotify vence em {overview.spotify_reauth_days} dias. Peça para reconectar.
            </motion.div>
          )}
          {error && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-6 flex items-center justify-between gap-4 rounded-2xl border border-heat/40 bg-heat/10 px-5 py-3 text-sm">
              <span>{error}</span>
              <button onClick={() => setError(null)} className="text-mute hover:text-paper">fechar</button>
            </motion.div>
          )}
        </AnimatePresence>

        <nav className="mt-10 flex gap-1 rounded-full border border-line bg-panel/60 p-1 backdrop-blur sm:w-fit">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`relative flex-1 whitespace-nowrap rounded-full px-2.5 py-2 text-sm font-medium transition sm:flex-none sm:px-5 ${tab === t.id ? 'text-ink' : 'text-mute hover:text-paper'}`}
            >
              {tab === t.id && <motion.span layoutId="tab" className="absolute inset-0 rounded-full bg-paper" transition={{ type: 'spring', duration: 0.4 }} />}
              <span className="relative">
                {t.label} <span className="font-mono text-xs opacity-60">{t.count}</span>
                {t.fresh > 0 && <span className="ml-1.5 inline-block h-2 w-2 rounded-full bg-heat align-middle" />}
              </span>
            </button>
          ))}
        </nav>

        <main className="mt-8">
          {tab === 'shows' && <ShowsView shows={shows} loading={busy && !shows.length} />}
          {tab === 'news' && <NewsView groups={news} loading={busy && !news.length} />}
          {tab === 'artists' && <ArtistsView artists={artists} onToggle={toggleMute} />}
        </main>
      </div>
    </div>
  )
}
