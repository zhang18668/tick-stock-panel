import type { ChanStructure } from '@/lib/api'

export function ChanDetails({ structures, selected, onSelect }: {
  structures: ChanStructure[]; selected?: ChanStructure; onSelect: (id: string) => void
}) {
  const centers = structures.filter(s => s.kind === 'center')
  const latest = centers.at(-1)
  const lastSegment = structures.filter(s => s.kind === 'segment').at(-1)
  const signals = structures.filter(s => s.kind === 'signal').sort((a, b) => b.end.index - a.end.index)
  const recent = structures.filter(s => s.kind !== 'fractal' && s.kind !== 'signal').sort((a, b) => b.end.index - a.end.index).slice(0, 24)
  const divergence = signals.find(s => s.features?.divergence_rate != null)

  function record(s: ChanStructure) {
    return <button key={s.id} type="button" data-structure-id={s.id} onClick={() => onSelect(s.id)}
      className={`w-full rounded-btn px-2 py-2 text-left transition-colors ${selected?.id === s.id ? 'bg-accent/10 text-accent' : 'text-secondary hover:bg-elevated'}`}>
      <span className="flex flex-wrap justify-between gap-1 text-xs"><span>{s.label}</span><span className="text-[10px] text-muted">{s.confirmedAt ? '已确认' : s.kind === 'signal' ? '形态信号' : '未确认'}</span></span>
      <span className="mt-1 block font-mono text-[10px] text-muted">{s.end.date} · {s.end.price.toFixed(2)}</span>
    </button>
  }

  return <aside aria-label="缠论结构详情" className="min-w-0 space-y-4 border-t border-border pt-4 xl:border-l xl:border-t-0 xl:pl-4 xl:pt-0">
    <section className="space-y-3 text-xs">
      <h2 className="text-sm font-medium text-foreground">结构概览</h2>
      <div className="flex justify-between gap-2"><span className="text-muted">当前结构</span><span className="text-secondary">{lastSegment ? `${lastSegment.label}${lastSegment.confirmedAt ? '' : ' · 未确认'}` : '结构不足'}</span></div>
      <div className="flex justify-between gap-2"><span className="text-muted">最近中枢</span><span className="font-mono text-secondary">{latest ? `${latest.low?.toFixed(2)}–${latest.high?.toFixed(2)}` : '暂无中枢'}</span></div>
      <div className="flex justify-between gap-2"><span className="text-muted">背驰力度比</span><span className="font-mono text-secondary">{divergence ? divergence.features!.divergence_rate.toFixed(3) : '条件不足'}</span></div>
      <p className="text-[10px] text-muted">力度比来自引擎信号特征；没有信号不代表没有背驰。</p>
    </section>
    {selected && <section aria-live="polite" className="space-y-2 rounded-card border border-accent/20 bg-accent/5 p-3 text-xs">
      <h3 className="font-medium text-foreground">{selected.label} · {selected.confirmedAt ? '已确认' : '未确认'}</h3>
      <p className="font-mono text-secondary">{selected.start.date} → {selected.end.date}</p>
      <p className="font-mono text-secondary">{selected.start.price.toFixed(2)} → {selected.end.price.toFixed(2)}</p>
      <p className="text-muted">确认时间：{selected.confirmedAt ?? '尚未确认'}</p>
      <p className="text-muted">{selected.basis}</p>
    </section>}
    <section>
      <h2 className="mb-1 text-sm font-medium text-foreground">近期信号 <span className="font-mono text-xs text-muted">{signals.length}</span></h2>
      {signals.length ? signals.slice(0, 12).map(record) : <p className="py-3 text-xs text-muted">暂无买卖点，等待结构形成</p>}
    </section>
    <section className="border-t border-border pt-3">
      <h2 className="mb-1 text-sm font-medium text-foreground">结构记录</h2>
      {recent.length ? recent.map(record) : <p className="py-3 text-xs text-muted">当前数据尚未形成有效笔或线段</p>}
    </section>
  </aside>
}
