import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { parts, type NewsGroup } from '../api'
import { Empty } from './Empty'

export function NewsView({ groups, loading }: { groups: NewsGroup[]; loading: boolean }) {
  if (loading) return <Empty title="Lendo as notícias…" />
  if (!groups.length)
    return <Empty title="Nenhum anúncio de show nas notícias" hint="Aqui aparecem shows que ainda não entraram nas bilheterias." />

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {groups.map((g, i) => (
        <NewsCard key={g.artist_key} group={g} index={i} />
      ))}
    </div>
  )
}

function NewsCard({ group, index }: { group: NewsGroup; index: number }) {
  const [open, setOpen] = useState(false)
  const [top, ...rest] = group.items
  const { day, month } = parts(top.date)

  return (
    <motion.article
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.4) }}
      className={`flex flex-col rounded-2xl border bg-panel p-5 ${group.is_new ? 'border-cool/60' : 'border-line'}`}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="truncate text-lg font-bold">{group.artist}</h3>
        {group.is_new && (
          <span className="shrink-0 rounded-full bg-cool px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider text-ink">novo</span>
        )}
      </div>

      <a href={top.link} target="_blank" rel="noreferrer" className="mt-3 block leading-snug text-paper/90 transition hover:text-cool">
        {top.title}
      </a>
      <p className="mt-2 font-mono text-xs text-mute">
        {day} {month} · {top.source || 'notícia'}
      </p>

      {rest.length > 0 && (
        <>
          <button onClick={() => setOpen(!open)} className="mt-4 self-start text-sm text-mute transition hover:text-paper">
            {open ? 'esconder' : `+${rest.length} ${rest.length === 1 ? 'notícia' : 'notícias'}`}
          </button>
          <AnimatePresence initial={false}>
            {open && (
              <motion.ul
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                {rest.map((n) => (
                  <li key={n.link} className="mt-3 border-t border-line pt-3">
                    <a href={n.link} target="_blank" rel="noreferrer" className="text-sm leading-snug text-paper/80 hover:text-cool">
                      {n.title}
                    </a>
                    <p className="mt-1 font-mono text-[11px] text-mute">
                      {parts(n.date).day} {parts(n.date).month} · {n.source || 'notícia'}
                    </p>
                  </li>
                ))}
              </motion.ul>
            )}
          </AnimatePresence>
        </>
      )}
    </motion.article>
  )
}
