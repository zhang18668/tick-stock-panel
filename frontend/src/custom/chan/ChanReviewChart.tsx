import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { EChartsCandlestick } from '@/components/EChartsCandlestick'
import { api, type ChanReviewSignal } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { ChanChart, ChartPill, LAYERS, type Layer } from './ChanChart'

export function ChanReviewChart({ item, owner }: { item: ChanReviewSignal; owner: string }) {
  const [mode, setMode] = useState<'original' | 'following'>('original')
  const [version, setVersion] = useState(item.snapshot_id)
  const [layers, setLayers] = useState<Layer[]>(['stroke', 'segment', 'center', 'signal'])
  const [indicators, setIndicators] = useState(['vol', 'macd'])
  const [revealed, setRevealed] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1000)
  const snapshot = useQuery({ queryKey: QK.chanReviewSnapshot(owner, version), queryFn: ({ signal }) => api.chanReviewSnapshot(version, signal), staleTime: Infinity })
  const detail = useQuery({ queryKey: QK.chanReviewSignal(owner, item.id), queryFn: ({ signal }) => api.chanReviewSignal(item.id, signal), staleTime: 30_000 })
  const following = useQuery({ queryKey: QK.chanReviewFollowing(owner, item.id), queryFn: ({ signal }) => api.chanReviewFollowing(item.id, signal), enabled: mode === 'following', staleTime: 60_000 })
  const original = snapshot.data?.symbol === item.symbol && snapshot.data.snapshot_id === version ? snapshot.data : undefined
  const future = following.data?.symbol === item.symbol && following.data.period === item.period ? following.data : undefined
  const cutoff = original?.observed_as_of ?? item.first_seen
  const initial = future?.rows.filter(r => r.date <= cutoff).length ?? 0
  const count = Math.min(revealed ?? initial, future?.rows.length ?? 0)
  const rows = useMemo(() => future?.rows.slice(0, count) ?? [], [future, count])
  const markers = useMemo(() => [{ date: item.point_date, kind: 'buy' as const, label: `B${item.point_type} 历史` }], [item])
  useEffect(() => {
    if (!playing || mode !== 'following' || !future || count >= future.rows.length) { setPlaying(false); return }
    const timer = window.setInterval(() => setRevealed(old => Math.min((old ?? initial) + 1, future.rows.length)), speed)
    return () => window.clearInterval(timer)
  }, [playing, mode, future, count, initial, speed])
  function changeMode(next: 'original' | 'following') { setMode(next); setPlaying(false); setRevealed(null) }
  const error = snapshot.error ?? (mode === 'following' ? following.error : null)
  const selected = original?.structures.find(s => s.id === item.structure_id)

  return <section className="min-w-0 rounded-card border border-border bg-surface p-3 sm:p-4">
    <header className="mb-3 flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
      <div><h2 className="text-sm font-medium text-foreground">{item.name} · <span className="font-mono">{item.symbol}</span> <span className="text-accent">B{item.point_type}</span></h2>
        <p className="mt-1 text-[11px] text-muted">落点 {item.point_date} · 首次观测 {item.first_seen} · 最近观测 {item.last_seen}</p></div>
      <div className="flex gap-2"><ChartPill active={mode === 'original'} onClick={() => changeMode('original')}>当时结构</ChartPill><ChartPill active={mode === 'following'} onClick={() => changeMode('following')}>后续走势</ChartPill></div>
    </header>
    <div className="mb-3 flex flex-wrap gap-2 text-[11px] text-muted">
      <span className="rounded bg-elevated px-2 py-1">{item.source === 'observed' ? '实盘观测' : '历史补算'}</span>
      {item.left_censored && <span className="rounded bg-elevated px-2 py-1">窗口开始前已存在，首次观测不代表最早生成日</span>}
      {item.status === 'not_seen' && <span className="rounded bg-elevated px-2 py-1">后续观测已不再出现，保留原记录</span>}
      {item.partial && <span>所属扫描覆盖不完整</span>}
    </div>
    {detail.data && detail.data.observations.length > 1 && <label className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted">归档版本
      <select aria-label="归档版本" value={version} onChange={e => { setVersion(e.target.value); setPlaying(false); setRevealed(null) }} className="rounded-btn border border-border bg-base p-1 text-secondary">
        {detail.data.observations.map(v => <option key={`${v.run_id}-${v.snapshot_id}`} value={v.snapshot_id}>{v.observed_as_of} · {v.created_at.slice(0, 19).replace('T', ' ')}</option>)}
      </select></label>}
    <div className="mb-3 flex flex-wrap items-center gap-1.5">
      {mode === 'original' && LAYERS.map(l => <ChartPill key={l.key} active={layers.includes(l.key)} onClick={() => setLayers(old => old.includes(l.key) ? old.filter(k => k !== l.key) : [...old, l.key])}>{l.label}</ChartPill>)}
      {['vol', 'macd'].map(key => <ChartPill key={key} active={indicators.includes(key)} onClick={() => setIndicators(old => old.includes(key) ? old.filter(k => k !== key) : [...old, key])}>{key === 'vol' ? '成交量' : 'MACD'}</ChartPill>)}
    </div>
    {mode === 'original' ? <p className="mb-2 text-[11px] text-muted">归档截止 {cutoff} · 当时前复权口径 · 买卖点为可变化的形态信号</p> : <>
      <p className="mb-2 text-[11px] text-muted">当前行情口径，仅标记历史信号日期；原价格结构请查看「当时结构」。周线按整周展开。</p>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <button type="button" className="rounded-btn border border-border px-2 py-1 disabled:opacity-40" disabled={!count} onClick={() => { setPlaying(false); setRevealed(Math.max(1, count - 1)) }}>上一根</button>
        <button type="button" className="rounded-btn border border-border px-2 py-1 disabled:opacity-40" disabled={!future || count >= future.rows.length} onClick={() => { setPlaying(false); setRevealed(count + 1) }}>下一根</button>
        <button type="button" className="rounded-btn bg-accent/10 px-2 py-1 text-accent disabled:opacity-40" disabled={!future || count >= future.rows.length} onClick={() => setPlaying(v => !v)}>{playing ? '暂停' : '播放'}</button>
        <select aria-label="播放速度" value={speed} onChange={e => setSpeed(Number(e.target.value))} className="rounded-btn border border-border bg-base p-1"><option value={2000}>0.5×</option><option value={1000}>1×</option><option value={500}>2×</option></select>
        <button type="button" onClick={() => { setPlaying(false); setRevealed(null) }} className="text-muted">回到观测日</button>
        <span className="font-mono text-muted">{rows.at(-1)?.date ?? '—'} · {count} / {future?.rows.length ?? 0} 根</span>
      </div>
    </>}
    {error ? <div role="alert" className="py-8 text-center text-sm text-danger">加载失败：{error.message}<button type="button" className="ml-3 text-accent" onClick={() => { void snapshot.refetch(); if (mode === 'following') void following.refetch() }}>重试</button></div>
      : !original || (mode === 'following' && following.isPending) ? <div className="py-16 text-center text-sm text-muted">归档图表加载中…</div>
      : mode === 'original' ? <ChanChart rows={original.rows} structures={original.structures} layers={layers} indicators={indicators} symbol={item.symbol} selected={selected} onDateClick={() => {}} />
      : rows.length ? <EChartsCandlestick data={rows} symbol={item.symbol} height={640} markers={markers} activeIndicators={indicators} showMA showInfoBar visibleBars={120} />
      : <div className="py-12 text-center text-sm text-muted">当前行情中暂无可展示的K线</div>}
    {mode === 'original' && original?.warnings.map(w => <p key={w} className="mt-2 text-[10px] text-muted">{w}</p>)}
    {mode === 'original' && original?.coverage && <p className="mt-2 text-[10px] text-muted">输入起点 {original.coverage.input_start} · 窗口前预热 {original.coverage.pre_window_rows} 根 · 最多 {original.coverage.input_limit} 根日K，并非完整上市历史</p>}
    <p className="mt-2 break-all font-mono text-[10px] text-muted">chan.py {item.engine_revision.slice(0, 12)} · 规则 {item.config_hash.slice(0, 12)}</p>
  </section>
}
