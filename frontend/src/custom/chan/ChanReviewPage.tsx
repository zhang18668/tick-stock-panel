import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { History, Plus, RefreshCw } from 'lucide-react'
import { api, type ChanReviewFilters, type ChanReviewRequest, type ChanReviewSignal } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { ChanReviewChart } from './ChanReviewChart'

const inputClass = 'min-w-0 rounded-btn border border-border bg-base px-2 py-1.5 text-xs text-secondary'
const buttonClass = 'rounded-btn border border-border px-3 py-1.5 text-xs text-secondary hover:bg-elevated disabled:opacity-40'
const activeStatuses = new Set(['queued', 'running', 'cancelling'])
const statuses: Record<string, string> = { queued: '排队中', running: '扫描中', cancelling: '正在取消', cancelled: '已取消', succeeded: '已完成', failed: '失败或部分完成', interrupted: '服务中断' }
function today() { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date()) }

export function ChanReviewPage() {
  const account = useQuery({ queryKey: ['account-me'], queryFn: api.accountMe, enabled: false })
  const owner = account.data?.id ?? 'standalone'
  return <ReviewPage key={owner} owner={owner} />
}

function ReviewPage({ owner }: { owner: string }) {
  const client = useQueryClient()
  const [filters, setFilters] = useState<ChanReviewFilters>({ source: 'backfill', period: 'day', category: '1', date_field: 'first_seen', start: '', end: '', point_type: '', q: '', page: 1 })
  const [selected, setSelected] = useState<ChanReviewSignal | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<ChanReviewRequest>(() => ({ source: 'backfill', period: 'day', scope: 'market', symbols: [], start: today(), end: today() }))
  const [codes, setCodes] = useState('')
  const [pendingDirection, setPendingDirection] = useState<'first' | 'last' | null>(null)
  const listing = useQuery({ queryKey: QK.chanReviewSignals(owner, filters), queryFn: ({ signal }) => api.chanReviewSignals(filters, signal), staleTime: 15_000 })
  const runs = useQuery({ queryKey: QK.chanReviewRuns(owner), queryFn: api.chanReviewRuns,
    refetchInterval: query => query.state.data?.items.some(r => activeStatuses.has(r.status)) ? 1500 : false })
  const invalidate = () => client.invalidateQueries({ queryKey: QK.chanReview(owner) })
  const create = useMutation({ mutationFn: (body: ChanReviewRequest) => api.chanReviewCreate(body), onSuccess: () => { setShowForm(false); void invalidate() } })
  const cancel = useMutation({ mutationFn: (id: string) => api.chanReviewCancel(id), onSuccess: () => { void invalidate() } })
  // A completed run changes the archive as well as the task list.
  const completedSignature = runs.data?.items.filter(r => !activeStatuses.has(r.status)).map(r => r.run_id).join(',')
  useEffect(() => { void client.invalidateQueries({ queryKey: ['chan-review', owner, 'signals'] }) }, [client, owner, completedSignature])
  useEffect(() => {
    if (!pendingDirection || !listing.data || listing.isFetching) return
    setSelected(pendingDirection === 'first' ? listing.data.items[0] ?? null : listing.data.items.at(-1) ?? null)
    setPendingDirection(null)
  }, [pendingDirection, listing.data, listing.isFetching])
  function change(next: Partial<ChanReviewFilters>) { setFilters(old => ({ ...old, ...next, page: next.page ?? 1 })); setSelected(null); setPendingDirection(null) }
  const items = listing.data?.items ?? []
  const index = items.findIndex(i => i.id === selected?.id)
  const pageCount = Math.max(1, Math.ceil((listing.data?.total ?? 0) / 30))
  function move(direction: -1 | 1) {
    const item = items[index + direction]
    if (item) { setSelected(item); return }
    const page = filters.page + direction
    if (page >= 1 && page <= pageCount) { setSelected(null); setFilters(old => ({ ...old, page })); setPendingDirection(direction === 1 ? 'first' : 'last') }
  }
  function submit() {
    create.mutate({ ...form, symbols: form.scope === 'symbols' ? codes.split(/[,，\s]+/).map(s => s.trim().toUpperCase()).filter(Boolean) : [] })
  }

  return <div className="space-y-4 p-3 sm:p-5">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="flex items-center gap-2 text-lg font-medium text-foreground"><History className="h-5 w-5 text-muted" />缠论复盘</h1>
        <p className="mt-1 text-xs text-muted">按 1买、2买、3买查历史信号，在图上回看后续走势</p></div>
      <div className="flex gap-2"><button type="button" className={buttonClass} onClick={() => { void invalidate() }} aria-label="刷新归档"><RefreshCw className="h-3.5 w-3.5" /></button>
        <button type="button" className="flex items-center gap-1.5 rounded-btn bg-accent px-3 py-1.5 text-xs text-white" onClick={() => { setShowForm(v => !v); create.reset() }}><Plus className="h-3.5 w-3.5" />新建扫描</button></div>
    </header>

    {showForm && <section className="space-y-3 rounded-card border border-border bg-surface p-4">
      <h2 className="text-sm font-medium text-foreground">盘后扫描 / 历史补算</h2>
      <p className="text-xs text-muted">使用本地已同步的股票日K。单次最多252个实际交易日；缺失行情会单独列出。实盘观测仅记录北京时间当天15:30之后的结果。</p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-[11px] text-muted">来源<select aria-label="扫描来源" className={inputClass} value={form.source} onChange={e => setForm(old => ({ ...old, source: e.target.value as ChanReviewRequest['source'], start: today(), end: today() }))}><option value="backfill">历史补算</option><option value="observed">实盘观测</option></select></label>
        <label className="grid gap-1 text-[11px] text-muted">周期<select aria-label="扫描周期" className={inputClass} value={form.period} onChange={e => setForm(old => ({ ...old, period: e.target.value as 'day' | 'week' }))}><option value="day">日线</option><option value="week">周线</option></select></label>
        <label className="grid gap-1 text-[11px] text-muted">范围<select aria-label="扫描范围" className={inputClass} value={form.scope} onChange={e => setForm(old => ({ ...old, scope: e.target.value as ChanReviewRequest['scope'] }))}><option value="market">全部股票</option><option value="watchlist">我的自选</option><option value="symbols">指定股票</option></select></label>
        {form.scope === 'symbols' && <label className="grid flex-1 gap-1 text-[11px] text-muted">股票代码<input aria-label="扫描股票代码" className={inputClass} placeholder="600000.SH, 000001.SZ" value={codes} onChange={e => setCodes(e.target.value)} /></label>}
        <label className="grid gap-1 text-[11px] text-muted">起始日期<input aria-label="扫描起始日期" className={inputClass} type="date" max={form.end} value={form.start} disabled={form.source === 'observed'} onChange={e => setForm(old => ({ ...old, start: e.target.value }))} /></label>
        <label className="grid gap-1 text-[11px] text-muted">结束日期<input aria-label="扫描结束日期" className={inputClass} type="date" min={form.start} max={today()} value={form.end} disabled={form.source === 'observed'} onChange={e => setForm(old => ({ ...old, end: e.target.value }))} /></label>
        <button type="button" className={buttonClass} disabled={create.isPending || !form.start || !form.end || form.start > form.end} onClick={submit}>{create.isPending ? '正在提交…' : '开始扫描'}</button>
      </div>
    </section>}
    {(create.error || cancel.error) && <p role="alert" className="text-sm text-danger">{(create.error ?? cancel.error)?.message}</p>}

    <details className="rounded-card border border-border bg-surface p-3" open={runs.data?.items.some(r => activeStatuses.has(r.status)) || undefined}>
      <summary className="cursor-pointer text-xs text-secondary">扫描任务 · {runs.data?.items.length ?? 0}</summary>
      {runs.isError && <p role="alert" className="mt-3 text-xs text-danger">任务加载失败：{runs.error.message}</p>}
      <div className="mt-3 max-h-64 space-y-2 overflow-auto">
        {!runs.data?.items.length && <p className="text-xs text-muted">暂无扫描任务，先新建盘后扫描或历史补算</p>}
        {runs.data?.items.map(run => <div key={run.run_id} className="rounded-btn border border-border p-3 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2"><span>{run.request.source === 'observed' ? '实盘观测' : '历史补算'} · {run.request.period === 'day' ? '日线' : '周线'} · {run.request.start} ~ {run.request.end}</span><span className="text-accent">{statuses[run.status] ?? run.status}</span></div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-muted"><span>{run.summary.processed ?? 0} / {run.summary.planned ?? run.request.symbols?.length ?? 0} · 完成 {run.summary.completed ?? 0} · 失败 {run.summary.failed ?? 0} · 缺行情 {run.summary.missing ?? 0}</span>
            {activeStatuses.has(run.status) ? <button type="button" className="text-accent disabled:opacity-40" disabled={cancel.isPending || run.status === 'cancelling'} onClick={() => cancel.mutate(run.run_id)}>取消任务</button>
              : run.status !== 'succeeded' && <button type="button" className="text-accent disabled:opacity-40" disabled={create.isPending} onClick={() => { const { source, period, scope, symbols, start, end } = run.request; create.mutate({ source, period, scope, symbols, start, end, resume_from: run.run_id }) }}>续跑未完成标的</button>}
          </div>
          {run.error && <p className="mt-2 text-danger">{run.error}</p>}
          {run.status === 'running' && <p className="mt-1 text-[10px] text-muted">{run.summary.phase === 'preparing_snapshot' ? '正在固定只读行情快照…' : '基于固定行情快照计算，实时更新不会中断扫描'}</p>}
          {run.summary.scope_note && <p className="mt-1 text-[10px] text-muted">{run.summary.scope_note}</p>}
          {run.summary.partial && <p className="mt-1 text-muted">覆盖不完整，已成功标的的归档仍可查看</p>}
          {run.summary.errors?.length ? <details className="mt-2 text-muted"><summary>失败明细</summary>{run.summary.errors.map((e, i) => <p key={i}>{e.symbol}：{e.message}</p>)}</details> : null}
        </div>)}
      </div>
    </details>

    <section className="space-y-3 rounded-card border border-border bg-surface p-3">
      <div className="flex flex-wrap gap-2">
        {(['1', '2', '3'] as const).map(category => <button type="button" key={category} aria-pressed={filters.category === category} onClick={() => change({ category, point_type: '' })}
          className={`min-w-24 rounded-btn px-4 py-2 text-sm ${filters.category === category ? 'bg-accent/15 text-accent' : 'bg-elevated text-muted'}`}>{category}买 <span className="ml-2 font-mono text-xs">{listing.data?.counts[category] ?? 0}</span></button>)}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="归档来源" className={inputClass} value={filters.source} onChange={e => change({ source: e.target.value as ChanReviewFilters['source'] })}><option value="backfill">历史补算</option><option value="observed">实盘观测</option></select>
        <select aria-label="归档周期" className={inputClass} value={filters.period} onChange={e => change({ period: e.target.value as 'day' | 'week' })}><option value="day">日线</option><option value="week">周线</option></select>
        <select aria-label="买点子类型" className={inputClass} value={filters.point_type} onChange={e => change({ point_type: e.target.value })}><option value="">全部子类型</option>{({ '1': ['1', '1p'], '2': ['2', '2s'], '3': ['3a', '3b'] }[filters.category]).map(t => <option key={t} value={t}>B{t}</option>)}</select>
        <select aria-label="日期口径" className={inputClass} value={filters.date_field} onChange={e => change({ date_field: e.target.value as ChanReviewFilters['date_field'] })}><option value="first_seen">首次观测日</option><option value="point_date">买点落点日</option></select>
        <input aria-label="筛选起始日期" className={inputClass} type="date" value={filters.start} max={filters.end || undefined} onChange={e => change({ start: e.target.value })} />
        <span className="text-xs text-muted">至</span><input aria-label="筛选结束日期" className={inputClass} type="date" value={filters.end} min={filters.start || undefined} onChange={e => change({ end: e.target.value })} />
        <input aria-label="搜索归档股票" className={`${inputClass} flex-1`} placeholder="股票代码 / 名称" value={filters.q} onChange={e => change({ q: e.target.value })} />
      </div>
    </section>

    <div className="grid min-w-0 gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
      <section className="min-w-0 rounded-card border border-border bg-surface p-3">
        <div className="mb-2 flex items-center justify-between text-xs text-muted"><span>{listing.data?.total ?? 0} 条归档信号</span><span>首次观测 / 落点</span></div>
        {listing.isPending || listing.isFetching ? <p className="py-8 text-center text-xs text-muted">归档加载中…</p>
          : listing.isError ? <div role="alert" className="py-8 text-xs text-danger">加载失败：{listing.error.message}<button type="button" onClick={() => { void listing.refetch() }} className="ml-2 text-accent">重试</button></div>
          : !items.length ? <div className="py-12 text-center"><p className="text-sm text-secondary">暂无已归档信号</p><p className="mt-2 text-xs text-muted">调整筛选，或新建扫描生成历史归档</p></div>
          : <div className="max-h-[720px] space-y-1 overflow-auto">{items.map(item => <button type="button" key={item.id} onClick={() => setSelected(item)} aria-pressed={selected?.id === item.id}
            className={`w-full rounded-btn border p-3 text-left ${selected?.id === item.id ? 'border-accent/40 bg-accent/10' : 'border-transparent hover:bg-elevated'}`}>
            <span className="flex items-center justify-between text-sm text-foreground"><span>{item.name}</span><span className="font-mono text-xs text-accent">B{item.point_type}</span></span>
            <span className="mt-1 flex items-center justify-between font-mono text-[10px] text-muted"><span>{item.symbol}</span><span>{item.first_seen} / {item.point_date}</span></span>
            {item.status === 'not_seen' && <span className="text-[10px] text-muted">后续已不再出现 · 原记录保留</span>}
          </button>)}</div>}
        <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted"><button type="button" className={buttonClass} disabled={filters.page <= 1 || listing.isFetching} onClick={() => change({ page: filters.page - 1 })}>上一页</button><span>{filters.page} / {pageCount}</span><button type="button" className={buttonClass} disabled={filters.page >= pageCount || listing.isFetching} onClick={() => change({ page: filters.page + 1 })}>下一页</button></div>
      </section>
      <div className="min-w-0 space-y-2">
        {selected ? <><div className="flex justify-between gap-2"><button type="button" className={buttonClass} disabled={index <= 0 && filters.page <= 1} onClick={() => move(-1)}>上一只</button><button type="button" className={buttonClass} disabled={index >= items.length - 1 && filters.page >= pageCount} onClick={() => move(1)}>下一只</button></div><ChanReviewChart key={`${owner}-${selected.id}`} item={selected} owner={owner} /></>
          : <div className="grid min-h-96 place-items-center rounded-card border border-border bg-surface p-6 text-center text-sm text-muted"><div><History className="mx-auto mb-3 h-8 w-8 opacity-50" /><p>选择一条信号查看当时结构</p><p className="mt-2 text-xs">原快照保留当时的笔、线段、中枢和买卖点；后续走势可逐根展开</p></div></div>}
      </div>
    </div>
  </div>
}
