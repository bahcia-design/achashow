export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-line px-6 py-16 text-center">
      <p className="text-lg font-semibold">{title}</p>
      {hint && <p className="mt-2 text-sm text-mute">{hint}</p>}
    </div>
  )
}
