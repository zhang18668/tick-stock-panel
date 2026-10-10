import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { QK } from '../../lib/queryKeys'
import { strategyLibraryApi, type StrategyGroup } from '../strategy-library/api'
import { optimizerApi, type OptimizerContract, type OptimizerRun, type OptimizerStrategy } from './api'

const activeStates = ['queued', 'running', 'cancelling']

type MetricRow = Record<string, unknown>

function formatPercent(value: unknown, absolute = false) {
  if (value == null || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${((absolute ? Math.abs(number) : number) * 100).toFixed(2)}%`
}

function formatFoldReturn(value: unknown) {
  if (value == null || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${number > 0 ? '+' : ''}${(number * 100).toFixed(2)}%`
}

function metricRows(value: unknown): MetricRow[] {
  return Array.isArray(value) ? value.filter(item => item && typeof item === 'object') as MetricRow[] : []
}

export function StrategyOptimizerPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const requestedIds = useMemo(() => {
    const ids = (location.state as { strategyIds?: unknown } | null)?.strategyIds
    return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === 'string') : []
  }, [location.state])
  const [strategies, setStrategies] = useState<OptimizerStrategy[]>([])
  const [strategyNames, setStrategyNames] = useState<Record<string, string>>({})
  const [groups, setGroups] = useState<StrategyGroup[]>([])
  const [selectedGroup, setSelectedGroup] = useState('')
  const [contract, setContract] = useState<OptimizerContract | null>(null)
  const [selected, setSelected] = useState('')
  const [run, setRun] = useState<OptimizerRun | null>(null)
  const [autoSaveRunId, setAutoSaveRunId] = useState('')
  const autoSaveStarted = useRef(new Set<string>())
  const [error, setError] = useState('')
  const [progress, setProgress] = useState<Record<string, unknown> | null>(null)
  const [start, setStart] = useState('2022-01-01')
  const [end, setEnd] = useState(new Date().toISOString().slice(0, 10))
  const [ranges, setRanges] = useState<Record<string, { min: number; max: number; step: number }>>({})
  const [discreteValues, setDiscreteValues] = useState<Record<string, Array<string | number | boolean>>>({})
  const [weights, setWeights] = useState({ oos_return: 0.55, drawdown_improvement: 0.2, win_rate: 0.15, trade_count: 0.1 })
  const [maxRounds, setMaxRounds] = useState(10)
  const [perRound, setPerRound] = useState(50)
  const [minTrades, setMinTrades] = useState(5)
  const [maxDrawdown, setMaxDrawdown] = useState(0.5)
  const [seed, setSeed] = useState(7)
  const [buySignals, setBuySignals] = useState<string[]>([])
  const [sellSignals, setSellSignals] = useState<string[]>([])
  const [trainFraction, setTrainFraction] = useState(0.6)
  const [testDays, setTestDays] = useState(63)
  const [stepDays, setStepDays] = useState(63)
  const [feesPct, setFeesPct] = useState(0.0002)
  const [slippageBps, setSlippageBps] = useState(5)
  const [commissionPct, setCommissionPct] = useState(0.0003)
  const [stampTaxPct, setStampTaxPct] = useState(0.0005)
  const [symbolsText, setSymbolsText] = useState('')
  const [matching, setMatching] = useState<'open_t+1' | 'close_t'>('open_t+1')
  const [mode, setMode] = useState<'position' | 'full'>('position')
  const [holdingDays, setHoldingDays] = useState(5)
  const [runs, setRuns] = useState<OptimizerRun[]>([])
  const saveMutation = useMutation({
    mutationFn: () => optimizerApi.saveRecommendations(run!.run_id),
    onSuccess: async result => {
      setError(result.errors.length ? `部分推荐未保存：${result.errors.map(item => `top${item.rank} ${item.error}`).join('；')}` : '')
      await queryClient.invalidateQueries({ queryKey: QK.strategyLibrary })
      await queryClient.invalidateQueries({ queryKey: QK.strategyOptimizerStrategies })
    },
    onError: reason => setError(String(reason)),
  })

  useEffect(() => {
    optimizerApi.strategies().then(setStrategies).catch(e => setError(String(e)))
    strategyLibraryApi.library().then(value => {
      setGroups(value.groups)
      setStrategyNames(Object.fromEntries(value.strategies.map(item => [item.id, item.name])))
    }).catch(e => setError(String(e)))
    optimizerApi.list().then(items => {
      setRuns(items)
      const scopedRuns = requestedIds.length ? items.filter(item => requestedIds.includes(String(item.config.strategy_id))) : items
      const latest = scopedRuns.find(item => activeStates.includes(item.state)) ?? scopedRuns[0]
      if (latest) {
        setRun(latest)
        if (latest.config.strategy_id) setSelected(String(latest.config.strategy_id))
      }
    }).catch(e => setError(String(e)))
  }, [requestedIds])
  useEffect(() => {
    if (!groups.length) return
    const runStrategyId = String(run?.config.strategy_id ?? '')
    const preferredGroup = groups.find(group => requestedIds.some(id => group.strategy_ids.includes(id)))
      ?? groups.find(group => group.strategy_ids.includes(runStrategyId))
    if (preferredGroup && (!selectedGroup || !groups.some(group => group.id === selectedGroup))) {
      setSelectedGroup(preferredGroup.id)
      const preferredStrategy = requestedIds.find(id => preferredGroup.strategy_ids.includes(id))
        ?? runStrategyId
      if (preferredStrategy) setSelected(preferredStrategy)
    }
  }, [groups, requestedIds, run?.config.strategy_id, selectedGroup])
  useEffect(() => {
    const preferred = requestedIds.find(id => strategies.some(item => item.strategy_id === id && item.optimizable))
    if (preferred && (!selected || !requestedIds.includes(selected))) setSelected(preferred)
  }, [strategies, selected, requestedIds])
  useEffect(() => {
    if (!selected) { setContract(null); return }
    optimizerApi.contract(selected).then(value => {
      setContract(value)
      setRanges(Object.fromEntries(value.parameters.filter(p => p.optimizable && p.minimum !== undefined && p.maximum !== undefined).map(p => [p.id, { min: p.minimum!, max: p.maximum!, step: p.step ?? 1 }])))
      setDiscreteValues(Object.fromEntries(value.parameters.filter(p => p.optimizable && (p.type === 'bool' || p.type === 'enum')).map(p => [p.id, p.type === 'bool' ? [true, false] : p.options as Array<string | number | boolean>])))
      setBuySignals(value.buy_signals); setSellSignals(value.sell_signals)
    }).catch(e => setError(String(e)))
  }, [selected])
  useEffect(() => {
    if (!run || !activeStates.includes(run.state)) return
    const source = new EventSource(optimizerApi.eventsUrl(run.run_id))
    source.onmessage = event => { try { const value = JSON.parse(event.data); if (value.type === 'snapshot_required') optimizerApi.get(run.run_id).then(setRun).catch(() => undefined); else setProgress(value) } catch { /* malformed event is ignored */ } }
    source.onerror = () => { /* EventSource reconnects automatically; polling remains a fallback. */ }
    const timer = window.setInterval(() => optimizerApi.get(run.run_id).then(setRun).catch(() => undefined), 1500)
    return () => { source.close(); window.clearInterval(timer) }
  }, [run?.run_id, run?.state])

  useEffect(() => {
    if (!run || run.run_id !== autoSaveRunId || run.state !== 'succeeded') return
    if (!Array.isArray(run.result?.top3) || !run.result.top3.length || autoSaveStarted.current.has(run.run_id)) return
    autoSaveStarted.current.add(run.run_id)
    saveMutation.mutate()
  }, [run, autoSaveRunId])

  const strategy = strategies.find(item => item.strategy_id === selected)
  const groupStrategyIds = new Set(groups.find(group => group.id === selectedGroup)?.strategy_ids ?? [])
  const visibleStrategies = strategies.filter(item => groupStrategyIds.has(item.strategy_id)
    && (!requestedIds.length || requestedIds.includes(item.strategy_id)))
  const resultStrategyId = String(run?.config.strategy_id ?? '')
  const resultContract = contract?.strategy_id === resultStrategyId ? contract : null
  const weightTotal = Object.values(weights).reduce((sum, value) => sum + value, 0)
  const setRange = (id: string, key: 'min' | 'max' | 'step', value: number) => setRanges(current => ({ ...current, [id]: { ...current[id], [key]: value } }))
  const toggle = (values: string[], setter: (values: string[]) => void, id: string) => setter(values.includes(id) ? values.filter(value => value !== id) : [...values, id])
  const toggleDiscrete = (id: string, value: string | number | boolean) => setDiscreteValues(current => {
    const existing = current[id] ?? []
    return { ...current, [id]: existing.includes(value) ? existing.filter(item => item !== value) : [...existing, value] }
  })

  const submit = () => {
    setError(''); setProgress(null)
    saveMutation.reset()
    const parameters = Object.fromEntries([
      ...Object.entries(ranges).map(([id, range]) => [id, range]),
      ...Object.entries(discreteValues).filter(([, values]) => values.length > 0).map(([id, values]) => [id, { values }]),
    ])
    optimizerApi.run({
      strategy_id: selected, asset_type: contract?.asset_type, start, end, parameters,
      buy_signals: buySignals, sell_signals: sellSignals, seed,
      max_rounds: maxRounds, candidates_per_round: perRound, total_candidates: maxRounds * perRound,
      weights, max_drawdown: maxDrawdown, min_trades: minTrades,
      train_fraction: trainFraction, test_days: testDays, step_days: stepDays,
      fees_pct: feesPct, slippage_bps: slippageBps,
      commission_pct: commissionPct, stamp_tax_pct: stampTaxPct,
      symbols: symbolsText.trim() ? symbolsText.split(',').map(value => value.trim()).filter(Boolean) : null,
      matching, mode, holding_days: holdingDays,
    }).then(value => {
      setAutoSaveRunId(value.run_id)
      setRun(value)
      setRuns(current => [value, ...current.filter(item => item.run_id !== value.run_id)])
    }).catch(e => setError(String(e)))
  }

  return <main className="mx-auto flex max-w-5xl flex-col gap-6 p-4 sm:p-6">
    <header><h1 className="text-2xl font-semibold">策略优化</h1><p className="mt-1 text-sm text-muted">只生成推荐，不会修改原策略。</p></header>
    {error && <div role="alert" className="rounded border border-red-500 p-3 text-red-500">{error}</div>}
    <section className="grid gap-5 rounded border p-4 sm:p-6">
      <label className="flex flex-col gap-2">策略分组<select aria-label="策略分组" value={selectedGroup} onChange={e => { setSelectedGroup(e.target.value); setSelected(''); setContract(null); setRun(null); setAutoSaveRunId(''); saveMutation.reset() }} className="rounded border bg-base p-2">
        <option value="">请先选择策略库分组</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
      </select></label>
      <label className="flex flex-col gap-2">策略<select value={selected} disabled={!selectedGroup} onChange={e => { setSelected(e.target.value); setRun(null); setAutoSaveRunId(''); saveMutation.reset() }} className="rounded border bg-base p-2">
        <option value="">请选择策略</option>{visibleStrategies.map(item => <option key={item.strategy_id} value={item.strategy_id}>{item.name}{item.optimizable ? '' : '（不可优化）'}</option>)}
      </select>{selectedGroup && !visibleStrategies.length && <span className="text-xs text-muted">该分组中没有可选择的策略{requestedIds.length ? '（当前批量选择范围内）' : ''}。</span>}</label>
      {strategy && !strategy.optimizable && <p className="text-sm text-muted">{strategy.reason}</p>}
      {contract && strategy?.optimizable && <>
        <div className="grid gap-3 sm:grid-cols-2">
          {contract.parameters.map(param => <fieldset key={param.id} className="rounded border p-3" disabled={!param.optimizable}>
            <legend className="px-1 text-sm">{param.label} <span className="text-muted">默认 {String(param.default)}</span></legend>
            {ranges[param.id] ? <div className="grid grid-cols-3 gap-2">
              {(['min', 'max', 'step'] as const).map(key => <label key={key} className="text-xs text-muted">{key === 'min' ? '最小值' : key === 'max' ? '最大值' : '步长'}<input type="number" value={ranges[param.id][key]} min={param.minimum} max={param.maximum} step={param.step ?? 1} onChange={e => setRange(param.id, key, Number(e.target.value))} className="mt-1 w-full rounded border bg-base p-2 text-sm" /></label>)}
            </div> : param.optimizable && (param.type === 'bool' || param.type === 'enum') ? <div className="flex flex-wrap gap-3">{(param.type === 'bool' ? [true, false] : param.options as Array<string | number | boolean>).map(value => <label key={String(value)} className="inline-flex items-center gap-1 text-sm"><input type="checkbox" checked={(discreteValues[param.id] ?? []).includes(value)} onChange={() => toggleDiscrete(param.id, value)} />{String(value)}</label>)}</div> : <p className="text-xs text-muted">固定为 {String(param.default)}</p>}
          </fieldset>)}
        </div>
        {contract.constraints?.length ? <p className="text-xs text-muted">策略约束（只读）：{JSON.stringify(contract.constraints)}</p> : null}
        <fieldset className="grid gap-2 sm:grid-cols-2"><legend className="text-sm font-medium">信号组合</legend>
          <div><p className="mb-1 text-xs text-muted">买入信号</p>{contract.buy_signals.map(signal => <label key={signal} className="mr-3 inline-flex items-center gap-1 text-sm"><input type="checkbox" checked={buySignals.includes(signal)} onChange={() => toggle(buySignals, setBuySignals, signal)} />{signal}</label>)}</div>
          <div><p className="mb-1 text-xs text-muted">卖出信号</p>{contract.sell_signals.map(signal => <label key={signal} className="mr-3 inline-flex items-center gap-1 text-sm"><input type="checkbox" checked={sellSignals.includes(signal)} onChange={() => toggle(sellSignals, setSellSignals, signal)} />{signal}</label>)}</div>
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">开始日期<input type="date" value={start} onChange={e => setStart(e.target.value)} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">结束日期<input type="date" value={end} onChange={e => setEnd(e.target.value)} className="mt-1 block w-full rounded border bg-base p-2" /></label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">最大轮数<input type="number" min={1} max={10} value={maxRounds} onChange={e => setMaxRounds(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">每轮候选数<input type="number" min={1} max={50} value={perRound} onChange={e => setPerRound(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">最大样本外回撤<input type="number" min={0} max={1} step={0.01} value={maxDrawdown} onChange={e => setMaxDrawdown(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">最低样本外交易数<input type="number" min={0} value={minTrades} onChange={e => setMinTrades(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">训练数据比例<input type="number" min={0.2} max={0.8} step={0.05} value={trainFraction} onChange={e => setTrainFraction(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">样本外窗口（天）<input type="number" min={10} max={500} value={testDays} onChange={e => setTestDays(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">滚动步长（天）<input type="number" min={1} max={500} value={stepDays} onChange={e => setStepDays(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">手续费率<input type="number" min={0} max={0.1} step={0.0001} value={feesPct} onChange={e => setFeesPct(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">滑点（基点）<input type="number" min={0} max={1000} value={slippageBps} onChange={e => setSlippageBps(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">佣金率<input type="number" min={0} max={0.1} step={0.0001} value={commissionPct} onChange={e => setCommissionPct(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">印花税率<input type="number" min={0} max={0.1} step={0.0001} value={stampTaxPct} onChange={e => setStampTaxPct(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">标的代码（逗号分隔，留空为全部）<input value={symbolsText} onChange={e => setSymbolsText(e.target.value)} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">成交时点<select value={matching} onChange={e => setMatching(e.target.value as typeof matching)} className="mt-1 block w-full rounded border bg-base p-2"><option value="open_t+1">次日开盘</option><option value="close_t">当日收盘</option></select></label>
          <label className="text-sm">回测模式<select value={mode} onChange={e => setMode(e.target.value as typeof mode)} className="mt-1 block w-full rounded border bg-base p-2"><option value="position">持仓模式</option><option value="full">完整模式</option></select></label>
          <label className="text-sm">持仓天数<input type="number" min={1} max={500} value={holdingDays} onChange={e => setHoldingDays(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
          <label className="text-sm">随机种子<input type="number" value={seed} onChange={e => setSeed(Number(e.target.value))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
        </div>
        <fieldset className="grid gap-3 sm:grid-cols-2"><legend className="text-sm font-medium">评分权重（合计 100%）</legend>{Object.entries(weights).map(([key, value]) => <label key={key} className="text-sm">{key}<input type="number" min={0} max={1} step={0.01} value={value} onChange={e => setWeights(current => ({ ...current, [key]: Number(e.target.value) }))} className="mt-1 block w-full rounded border bg-base p-2" /></label>)}</fieldset>
        <p className="text-xs text-muted">当前权重合计：{(weightTotal * 100).toFixed(0)}%</p>
        <button className="w-fit rounded bg-primary px-4 py-2 text-white disabled:opacity-50" disabled={!start || !end || start >= end || Math.abs(weightTotal - 1) > 1e-9 || Object.values(discreteValues).some(values => values.length === 0) || !!run} onClick={submit}>启动优化</button>
      </>}
    </section>
    {runs.length > 0 && <section className="rounded border p-4"><h2 className="mb-3 font-medium">最近优化任务</h2><ul className="grid gap-2">{runs.slice(0, 10).map(item => {
      const strategyId = String(item.config.strategy_id ?? '')
      const strategyName = (strategyNames[strategyId] ?? strategyId) || '策略'
      return <li key={item.run_id}><button className="flex w-full items-center justify-between rounded border p-3 text-left" onClick={() => optimizerApi.get(item.run_id).then(value => { setRun(value); saveMutation.reset(); if (value.config.strategy_id) setSelected(String(value.config.strategy_id)) })}><span>{strategyName} · {item.run_id.slice(0, 8)}</span><span>{item.state}</span></button></li>
    })}</ul></section>}
    {run && <section className="rounded border p-4 sm:p-6">
      <h2 className="font-medium">任务状态：{run.state}</h2>
      {progress && <p className="mt-2 text-sm text-muted">进度：{JSON.stringify(progress)}</p>}
      {run.error && <p className="mt-2 text-red-500">{run.error}</p>}
      {activeStates.includes(run.state) && <button className="mt-3 rounded border px-4 py-2" onClick={() => optimizerApi.cancel(run.run_id).then(setRun)}>取消</button>}
      {['interrupted', 'failed'].includes(run.state) && <button className="mt-3 rounded border px-4 py-2" onClick={() => optimizerApi.resume(run.run_id).then(setRun)}>恢复任务</button>}
      {run.result && <>
        <p className="mt-2 text-sm text-muted">优化区间：{String(run.config.start ?? '—')} 至 {String(run.config.end ?? '—')}；停止原因：{String(run.result.stop_reason ?? '—')}；已评估 {String(run.result.evaluated_candidates ?? 0)} 个候选；数据指纹 {String(run.config.input_fingerprint ?? '—').slice(0, 12)}</p>
        {Array.isArray(run.result.training_candidates) && <p className="mt-1 text-xs text-muted">训练候选失败数：{(run.result.training_candidates as Record<string, unknown>[]).filter(item => Boolean(item.training_error)).length}</p>}
        {run.result.insufficient_recommendations === true && <p className="mt-2 text-sm text-amber-600">通过回撤、交易数等门槛的候选不足 3 个，以下仅展示可用推荐。</p>}
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{((run.result.top3 as Record<string, unknown>[]) ?? []).map((item, index) => {
          const metrics = (item.oos_metrics && typeof item.oos_metrics === 'object' ? item.oos_metrics : {}) as MetricRow
          const folds = metricRows(metrics.fold_metrics).length
            ? metricRows(metrics.fold_metrics)
            : metricRows(item.folds).map(fold => ((fold.metrics && typeof fold.metrics === 'object') ? fold.metrics : fold) as MetricRow)
          const parameters = (item.parameters && typeof item.parameters === 'object' ? item.parameters : {}) as Record<string, unknown>
          const foldValues = folds.map(fold => Number(fold.total_return)).filter(Number.isFinite)
          const maxFoldAbs = Math.max(...foldValues.map(Math.abs), 0.0001)
          const config = run.config
          const loadBacktest = () => navigate('/backtest?tab=strategy', { state: { loadCandidate: {
            name: `策略优化推荐 ${index + 1}`,
            config: {
              strategy_id: resultStrategyId,
              asset_type: config.asset_type,
              symbols: config.symbols ?? [],
              start: config.start,
              end: config.end,
              params: parameters,
              entry_fill: config.matching,
              exit_fill: config.matching,
              commission_pct: config.commission_pct ?? config.fees_pct,
              stamp_tax_pct: config.stamp_tax_pct,
              slippage_bps: config.slippage_bps,
              mode: config.mode,
              holding_days: config.holding_days,
              overrides: {
                entry_signals: item.buy_signals ?? config.buy_signals ?? [],
                exit_signals: item.sell_signals ?? config.sell_signals ?? [],
              },
            },
          } } })
          return <article key={String(item.candidate_id ?? index)} className="min-w-0 rounded border bg-surface p-4">
            <div className="flex items-start justify-between gap-3"><div><h3 className="font-medium">推荐 {index + 1}</h3><p className="mt-1 text-xs text-muted">综合评分 {Number(item.score ?? 0).toFixed(3)}</p></div><button type="button" onClick={loadBacktest} className="shrink-0 rounded border border-accent/40 px-2.5 py-1.5 text-xs font-medium text-accent hover:bg-accent/10">载入回测</button></div>
            <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded border bg-border sm:grid-cols-4 xl:grid-cols-2 2xl:grid-cols-4">
              {[
                ['样本外收益', formatPercent(metrics.oos_return)],
                ['样本外最大回撤', formatPercent(metrics.max_oos_drawdown, true)],
                ['胜率', formatPercent(metrics.win_rate)],
                ['交易数', metrics.trade_count == null ? '—' : `${String(metrics.trade_count)} 笔`],
              ].map(([label, value]) => <div key={label} className="min-w-0 bg-base px-2.5 py-2"><div className="truncate text-[10px] text-muted">{label}</div><div className={`mt-0.5 font-mono text-sm font-semibold ${label === '样本外收益' ? Number(metrics.oos_return) > 0 ? 'text-red-500' : Number(metrics.oos_return) < 0 ? 'text-emerald-600' : 'text-foreground' : 'text-foreground'}`}>{value}</div></div>)}
            </div>
            <div className="mt-3"><h4 className="text-xs font-medium text-secondary">推荐参数</h4><dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1.5">{Object.entries(parameters).map(([key, value]) => {
              const definition = resultContract?.parameters.find(param => param.id === key)
              const changed = definition && JSON.stringify(value) !== JSON.stringify(definition.default)
              return <div key={key} className="min-w-0"><dt className="truncate text-[10px] text-muted" title={definition?.label ?? key}>{definition?.label ?? key}</dt><dd className="truncate text-xs text-foreground" title={changed ? `默认 ${String(definition?.default)} → 推荐 ${String(value)}` : String(value)}>{changed && <span className="mr-1 text-muted">{String(definition?.default)} →</span>}{String(value)}</dd></div>
            })}</dl></div>
            <div className="mt-4"><h4 className="text-xs font-medium text-secondary">逐折收益 <span className="font-normal text-muted">({folds.length} 折)</span></h4>
              {folds.length ? <div className="mt-1.5 space-y-1">{folds.map((fold, foldIndex) => {
                const value = Number(fold.total_return)
                const finite = Number.isFinite(value)
                const width = finite ? `${Math.max(1, Math.abs(value) / maxFoldAbs * 100)}%` : '0%'
                return <div key={foldIndex} className="grid grid-cols-[34px_minmax(0,1fr)_58px] items-center gap-2 text-[10px]" role="img" aria-label={`第 ${foldIndex + 1} 折收益 ${formatFoldReturn(fold.total_return)}`}>
                  <span className="text-muted">第 {foldIndex + 1} 折</span>
                  <div className="relative h-4 rounded bg-elevated" aria-hidden="true"><div className="absolute inset-y-0 left-1/2 w-px bg-border" />{finite && <div className={`absolute inset-y-0 ${value >= 0 ? 'left-1/2 rounded-r bg-red-500' : 'right-1/2 rounded-l bg-emerald-500'}`} style={{ width }} />}</div>
                  <span className={`text-right font-mono ${value > 0 ? 'text-red-500' : value < 0 ? 'text-emerald-600' : 'text-foreground'}`}>{formatFoldReturn(fold.total_return)}</span>
                </div>
              })}</div> : <p className="mt-1 text-xs text-muted">没有逐折指标</p>}
            </div>
          </article>
        })}</div>
        {((run.result.top3 as unknown[]) ?? []).length === 0 && <p className="mt-3 text-sm text-muted">没有候选通过硬性筛选门槛，请调整范围或条件后重试。</p>}
        {run.state === 'succeeded' && ((run.result.top3 as unknown[]) ?? []).length > 0 && <div className="mt-4 flex flex-wrap items-center gap-3 border-t pt-4"><span role="status" className="text-sm text-muted">{saveMutation.isPending ? '正在自动保存前三名到策略库…' : saveMutation.data ? `已自动保存 ${saveMutation.data.saved.length} 个策略${saveMutation.data.saved.length ? `：${saveMutation.data.saved.map(item => item.name).join('、')}` : ''}` : ''}</span>{saveMutation.data?.errors.length ? <button type="button" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} className="rounded border px-3 py-1.5 text-sm disabled:opacity-50">重试保存</button> : null}</div>}
      </>}
    </section>}
  </main>
}
