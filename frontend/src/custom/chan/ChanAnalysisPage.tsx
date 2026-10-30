import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChartNoAxesCombined, RefreshCw } from 'lucide-react'
import { api, type ChanBar } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { klineDailyQueryOptions } from '@/lib/kline'
import { toOHLC } from '@/components/StockDailyKChart'
import { StockFinancialSearch } from '@/components/financials/StockFinancialSearch'
import { ChanChart, ChartPill, LAYERS, type Layer } from './ChanChart'
import { ChanDetails } from './ChanDetails'

function queryRange() {
  const end = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date())
  const start = new Date(`${end}T00:00:00Z`)
  start.setUTCFullYear(start.getUTCFullYear() - 3)
  return { start: start.toISOString().slice(0, 10), end }
}

export function ChanAnalysisPage() {
  const queryClient = useQueryClient()
  const [stock, setStock] = useState<{ symbol: string; name: string } | null>(null)
  const [period, setPeriod] = useState<'day' | 'week'>('day')
  const [cutoff, setCutoff] = useState('')
  const [layers, setLayers] = useState<Layer[]>(['stroke', 'segment', 'center', 'signal'])
  const [indicators, setIndicators] = useState(['vol', 'macd'])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [range] = useState(queryRange)
  const symbol = stock?.symbol ?? ''
  const daily = useQuery({ ...klineDailyQueryOptions(symbol, range), enabled: !!symbol })
  const sourceRows = useMemo(() => daily.data?.symbol === symbol && !daily.isPlaceholderData ? toOHLC(daily.data.rows) : [], [daily.data, daily.isPlaceholderData, symbol])
  const inputRows = useMemo<ChanBar[]>(() => sourceRows.filter(r => !cutoff || r.date <= cutoff).map(r => ({
    date: r.date, open: r.open, high: r.high, low: r.low, close: r.close, volume: r.volume,
  })), [sourceRows, cutoff])
  const analysis = useQuery({
    queryKey: QK.chanAnalysis(symbol, period, inputRows),
    queryFn: ({ signal }) => api.chanAnalyze(symbol, period, inputRows, signal),
    enabled: !!symbol && !daily.isError && inputRows.length > 0,
    staleTime: 60_000, gcTime: 60_000,
  })
  const result = !daily.isError && analysis.data?.symbol === symbol && analysis.data.period === period ? analysis.data : undefined
  const rows = useMemo(() => {
    const sourceByDate = new Map(sourceRows.map(r => [r.date, r]))
    return (result?.rows ?? []).map(r => period === 'day' ? { ...sourceByDate.get(r.date), ...r } : r)
  }, [result, sourceRows, period])
  const structures = result?.structures ?? []
  const selected = structures.find(s => s.id === selectedId)
  const current = rows.at(-1)
  const previous = rows.at(-2)
  const change = current && previous ? (current.close / previous.close - 1) * 100 : null
  const mismatch = !!daily.data && daily.data.symbol !== symbol && !daily.isFetching
  const error = daily.isError || analysis.isError || mismatch
  const busy = !!symbol && (daily.isLoading || (inputRows.length > 0 && analysis.isPending))

  function selectStock(next: string, name: string) {
    setStock({ symbol: next, name }); setSelectedId(null); setCutoff('')
  }
  function changePeriod(next: 'day' | 'week') { setPeriod(next); setSelectedId(null) }
  function toggleLayer(key: Layer) { setLayers(old => old.includes(key) ? old.filter(k => k !== key) : [...old, key]) }
  async function refresh() {
    const refreshed = await daily.refetch()
    if (!refreshed.isError) {
      // Eligibility changes at the close even if the OHLC values are identical.
      await queryClient.invalidateQueries({ queryKey: QK.chanAnalyses(symbol), refetchType: 'active' }, { cancelRefetch: false })
    }
  }

  return <div className="space-y-4 p-3 sm:p-5">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <ChartNoAxesCombined className="h-5 w-5 text-muted" />
        <h1 className="text-lg font-medium text-foreground">缠论分析</h1>
        <span className="rounded bg-elevated px-2 py-0.5 font-mono text-[10px] text-muted">chan.py</span>
      </div>
      <div className="w-full sm:max-w-md"><StockFinancialSearch onSelect={selectStock} assetTypes="stock" /></div>
    </header>

    {!stock ? <div className="rounded-card border border-border bg-surface px-5 py-16 text-center">
      <ChartNoAxesCombined className="mx-auto mb-4 h-8 w-8 text-muted" />
      <p className="text-sm text-secondary">输入股票代码或名称，自动绘制缠论结构</p>
      <p className="mt-2 text-xs text-muted">笔 · 线段 · 中枢 · 买卖点，由 chan.py 计算</p>
    </div> : <section className="rounded-card border border-border bg-surface p-3 sm:p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="font-medium text-foreground">{stock.name} · <span className="font-mono">{symbol}</span></h2>
          {current && <span className={`font-mono text-sm ${change != null && change < 0 ? 'text-bear' : 'text-bull'}`}>{current.close.toFixed(2)} <span className="text-xs">{change == null ? '—' : `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}</span></span>}
          {current && <span className="text-[10px] text-muted">{current.date} · {period === 'day' ? '日线' : '周线'} · 前复权接口口径</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ChartPill active={period === 'day'} onClick={() => changePeriod('day')}>日线</ChartPill>
          <ChartPill active={period === 'week'} onClick={() => changePeriod('week')}>周线</ChartPill>
          <button type="button" onClick={() => { void refresh() }} disabled={daily.isFetching || analysis.isFetching}
            className="flex items-center gap-1 rounded-btn px-2 py-1 text-xs text-muted hover:bg-elevated hover:text-foreground disabled:opacity-40">
            <RefreshCw className={`h-3 w-3 ${daily.isFetching || analysis.isFetching ? 'animate-spin' : ''}`} />刷新
          </button>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {LAYERS.map(layer => <ChartPill key={layer.key} active={layers.includes(layer.key)} onClick={() => toggleLayer(layer.key)}>{layer.label} <span className="opacity-60">{structures.filter(s => s.kind === layer.key).length}</span></ChartPill>)}
        <span className="mx-1 h-3 border-l border-border" aria-hidden="true" />
        {([['vol', '成交量'], ['macd', 'MACD']] as const).map(([key, label]) => <ChartPill key={key} active={indicators.includes(key)} onClick={() => setIndicators(old => old.includes(key) ? old.filter(k => k !== key) : [...old, key])}>{label}</ChartPill>)}
        <label className="ml-auto flex flex-wrap items-center gap-2 text-[10px] text-muted">历史截止
          <input type="date" aria-label="历史截止日期" value={cutoff} max={range.end}
            onChange={e => { setCutoff(e.target.value); setSelectedId(null) }}
            className="min-w-0 rounded-btn border border-border bg-base px-2 py-1 text-xs text-secondary" />
        </label>
        {cutoff && <button type="button" className="px-2 text-xs text-accent" onClick={() => { setCutoff(''); setSelectedId(null) }}>回到最新</button>}
      </div>

      <div aria-live="polite">
        {busy && <div className="py-12 text-center text-sm text-muted">{daily.isLoading ? 'K线加载中…' : 'chan.py 计算中…'}</div>}
        {error && <div role="alert" className="space-y-2 rounded-btn bg-elevated p-4 text-sm text-danger">
          <p>{daily.isError || mismatch ? 'K线加载失败' : '缠论计算失败'}：{mismatch ? '响应标的不匹配' : (daily.error ?? analysis.error)?.message}</p>
          <button type="button" onClick={() => { if (daily.isError || mismatch) void daily.refetch(); else void analysis.refetch() }} className="rounded-btn border border-border px-3 py-1 text-secondary">重试</button>
        </div>}
        {!busy && !error && inputRows.length === 0 && <div className="py-12 text-center text-sm text-muted">暂无K线数据，请调整截止日或先在数据页面同步日K</div>}
      </div>

      {!error && !busy && rows.length > 0 && <>
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-muted">
          <span className="font-mono">{result?.ruleVersion}</span><span>实线：已确认结构</span><span>虚线 / ?：未确认结构或形态信号</span><span>分析截止 {result?.asOf ?? '条件不足'} · {rows.length} 根</span>
        </div>
        <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_248px]">
          <div className="min-w-0">
            <ChanChart key={`${symbol}:${period}`} rows={rows} structures={structures} layers={layers} indicators={indicators} symbol={symbol}
              selected={selected} stockInfo={daily.data?.stock_info} onDateClick={date => setSelectedId(structures.find(s => s.end.date === date)?.id ?? null)} />
            <div className="mt-2 space-y-1 border-t border-border pt-2 text-[10px] text-muted">
              {result?.warnings.map(w => <p key={w}>{w}</p>)}
              <p className="font-mono">引擎 {result?.engine.name} · {result?.engine.revision.slice(0, 12)} · MACD peak / 背驰阈值 0.9</p>
            </div>
          </div>
          <ChanDetails structures={structures} selected={selected} onSelect={setSelectedId} />
        </div>
      </>}
    </section>}
  </div>
}
