import { motion } from 'motion/react'
import { daysUntil, monthLabel, parts, type Show } from '../api'
import { Empty } from './Empty'

export function ShowsView({ shows, loading }: { shows: Show[]; loading: boolean }) {
  if (loading) return <Empty title="Procurando shows…" />
  if (!shows.length)
    return <Empty title="Nenhum show no radar ainda" hint="A busca roda todo dia às 9h e checa ~30 artistas por vez." />

  // Agrupa por mês
  const groups: { label: string; items: Show[] }[] = []
  for (const s of shows) {
    const label = monthLabel(s.date)
    const last = groups[groups.length - 1]
    if (last?.label === label) last.items.push(s)
    else groups.push({ label, items: [s] })
  }

  let i = 0
  return (
    <div className="space-y-10">
      {groups.map((g) => (
        <section key={g.label}>
          <h2 className="mb-4 font-mono text-xs uppercase tracking-[0.2em] text-mute">{g.label}</h2>
          <div className="space-y-4">
            {g.items.map((s) => (
              <ShowCard key={s.id} show={s} index={i++} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function ShowCard({ show, index }: { show: Show; index: number }) {
  const { day, month, weekday } = parts(show.date)
  const days = daysUntil(show.date)
  const when = days === 0 ? 'hoje' : days === 1 ? 'amanhã' : `em ${days} dias`

  return (
    <motion.a
      href={show.url}
      target="_blank"
      rel="noreferrer"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.4) }}
      whileHover={{ y: -3 }}
      className={`ticket group relative flex overflow-visible rounded-2xl border bg-panel transition-colors ${
        show.is_new ? 'border-heat/60 shadow-[0_0_40px_-12px] shadow-heat/50' : 'border-line hover:border-mute/60'
      }`}
    >
      <div className="flex w-[5.5rem] shrink-0 flex-col items-center justify-center border-r border-dashed border-line py-5 max-sm:w-[4.5rem]">
        <span className="font-mono text-[10px] uppercase tracking-widest text-mute">{weekday}</span>
        <span className="text-4xl font-extrabold leading-none max-sm:text-3xl">{day}</span>
        <span className="font-mono text-xs uppercase tracking-widest text-heat">{month}</span>
      </div>

      <div className="flex min-w-0 flex-1 items-center justify-between gap-4 px-5 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-xl font-bold sm:text-2xl">{show.artist}</h3>
            {show.is_new && (
              <span className="shrink-0 rounded-full bg-heat px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider text-ink">novo</span>
            )}
          </div>
          <p className="truncate text-sm text-mute">
            {show.venue}
            {show.city && <> · {show.city}</>}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-mono text-xs text-mute">{when}</p>
          <p className="mt-1 text-sm font-semibold text-heat opacity-0 transition group-hover:opacity-100 max-sm:opacity-100">ver →</p>
        </div>
      </div>
    </motion.a>
  )
}
