import type { RobustResult, RobustSegment } from './api'

const pct = (value: unknown) => {
  const number = Number(value)
  return value == null || !Number.isFinite(number) ? '—' : `${(number * 100).toFixed(2)}%`
}

const points = (value: unknown) => {
  const number = Number(value)
  return value == null || !Number.isFinite(number) ? '—' : `${number >= 0 ? '+' : ''}${(number * 100).toFixed(2)} 个百分点`
}

function segments(candidate: Record<string, unknown>): RobustSegment[] {
  return Array.isArray(candidate.segments) ? candidate.segments.map(row => {
    const item = row as Record<string, unknown>
    const metrics = (item.metrics && typeof item.metrics === 'object' ? item.metrics : {}) as Record<string, unknown>
    return {
      window_id: String(item.window_id ?? ''), annualized_return: metrics.annualized_return == null ? null : Number(metrics.annualized_return),
      max_drawdown: metrics.max_drawdown == null ? null : Number(metrics.max_drawdown), trade_count: metrics.trade_count == null ? null : Number(metrics.trade_count),
      baseline_delta: metrics.baseline_delta == null ? null : Number(metrics.baseline_delta), percentile: null,
      failures: item.failure ? [String(item.failure)] : [],
    }
  }) : []
}

export function RobustnessResults({
  result,
  onSave,
  savingRank,
  savedRanks,
}: {
  result: RobustResult
  onSave?: (rank: number) => void
  savingRank?: number | null
  savedRanks?: Set<number>
}) {
  return <section className="mt-4 space-y-4" aria-label="跨时期稳健结果">
    <div className="rounded border p-3 text-sm">
      <h3 className="font-medium">开发区间分段评估</h3>
      <p className="mt-1 text-xs text-muted">各段独立起始资金与空仓；开发数据参与筛选，不代表独立样本外。</p>
      <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[620px] text-left text-xs"><thead><tr><th>候选</th>{result.time_plan.development.map(window => <th key={window.id}>{window.id}<br />{window.start} — {window.end}</th>)}</tr></thead>
        <tbody>{result.top3.map((candidate, index) => <tr key={String(candidate.candidate_id)} className="border-t"><td className="py-2">推荐 {index + 1}<br />R {pct(candidate.robust_score)}{onSave && <div className="mt-1">{savedRanks?.has(index + 1) ? <span role="status" className="text-emerald-600">已添加</span> : <button type="button" onClick={() => onSave(index + 1)} disabled={savingRank != null} className="rounded border px-2 py-1 text-xs disabled:opacity-50">{savingRank === index + 1 ? '添加中…' : '添加到自定义策略'}</button>}</div>}</td>{segments(candidate).map(row => <td key={row.window_id} className="py-2">年化 {pct(row.annualized_return)}<br />回撤 {pct(row.max_drawdown)} · {row.trade_count ?? '—'} 笔<br />相对默认 {points(row.baseline_delta)}{row.failures.length > 0 && <span className="block text-red-500">{row.failures.join('；')}</span>}</td>)}</tr>)}</tbody></table></div>
    </div>
    {result.continuous_development && <div className="rounded border p-3 text-sm"><h3 className="font-medium">连续开发区间（跨段持仓）</h3><p className="text-xs text-muted">{result.continuous_development.window.start} — {result.continuous_development.window.end}；独立回测曲线，不参与推荐排序。</p>
      {result.continuous_development.candidates.map(row => { const metrics = (row.metrics && typeof row.metrics === 'object' ? row.metrics : {}) as Record<string, unknown>; return <p key={String(row.candidate_id)} className="mt-1">{String(row.candidate_id)}：年化 {pct(metrics.annualized_return)} · 回撤 {pct(metrics.max_drawdown)} · {String(metrics.trade_count ?? '—')} 笔 · 相对默认 {points(metrics.baseline_delta)}</p> })}
    </div>}
    {result.diagnostics.length > 0 && <div className="rounded border p-3 text-sm"><h3 className="font-medium">开发数据滚动诊断</h3><p className="text-xs text-muted">两年窗口每六个月移动；重叠窗口不是独立样本，不参与推荐排序。</p>
      {result.diagnostics.map(row => { const window = (row.window ?? {}) as Record<string, unknown>; const candidates = Array.isArray(row.candidates) ? row.candidates as Array<Record<string, unknown>> : []; return <div key={String(window.id)} className="mt-2"><p>{String(window.start)} — {String(window.end)}</p>{candidates.map(item => { const metrics = (item.metrics && typeof item.metrics === 'object' ? item.metrics : {}) as Record<string, unknown>; return <p key={String(item.candidate_id)} className="text-xs">{String(item.candidate_id)}：年化 {pct(metrics.annualized_return)} · 回撤 {pct(metrics.max_drawdown)} · 相对默认 {points(metrics.baseline_delta)}</p> })}</div> })}
    </div>}
    {Object.keys(result.references ?? {}).length > 0 && <div className="rounded border p-3 text-sm"><h3 className="font-medium">固定参考策略（默认参数）</h3>{Object.entries(result.references ?? {}).map(([strategyId, rows]) => <div key={strategyId}><p>{strategyId}</p>{rows.map(row => <p key={row.window_id} className="text-xs">{row.window_id}：{row.metrics ? `年化 ${pct(row.metrics.annualized_return)} · 回撤 ${pct(row.metrics.max_drawdown)} · ${row.metrics.trade_count} 笔` : row.failure ?? '数据不可用'}</p>)}</div>)}</div>}
    {result.coverage?.warnings?.map(warning => <p key={warning} role="status" className="text-amber-600">{warning}</p>)}
    <div className="rounded border p-3 text-sm"><h3 className="font-medium">留出验证</h3>
      {!result.time_plan.holdout ? <p className="mt-1 text-muted">未设置留出区间：此模式不提供独立留出结论。</p> : <><p className="mt-1">{result.time_plan.holdout.start} — {result.time_plan.holdout.end} · 状态：{result.holdout.status}{result.holdout.reuse === 'repeated' ? ' · 区间已重复使用' : result.holdout.reuse === 'interrupted' ? ' · 上次验证中断' : ''}</p><p className="text-xs text-muted">用途声明：{String(result.holdout.usage)}</p>
        {result.holdout.failure && <p role="status" className="text-amber-600">{result.holdout.failure}</p>}
        {result.holdout.results.map(row => { const metrics = (row.metrics && typeof row.metrics === 'object' ? row.metrics : {}) as Record<string, unknown>; return <p key={String(row.candidate_id)} className="text-xs">{String(row.candidate_id)}：年化 {pct(metrics.annualized_return)} · 回撤 {pct(metrics.max_drawdown)} · {String(metrics.trade_count ?? '—')} 笔 · 相对默认 {points(metrics.baseline_delta)}</p> })}</>}
    </div>
    {result.top3.length === 0 && <p role="status" className="text-amber-600">没有候选通过全部门槛及邻域稳定性要求。</p>}
  </section>
}
