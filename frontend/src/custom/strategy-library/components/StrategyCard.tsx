import type { StrategyGroup, StrategyResult, StrategySummary } from '../api'

type Props = {
  strategy: StrategySummary
  groups: StrategyGroup[]
  results: Partial<Record<'3m' | '6m' | '12m', StrategyResult>>
  groupId: string
  onGroup: (groupId: string) => void
  onDetails: () => void
  onRun: () => void
}
const periods = [['3m', '近 3 个月'], ['6m', '近半年'], ['12m', '近一年']] as const
const percent = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`

export function StrategyCard({ strategy, groups, results, groupId, onGroup, onDetails, onRun }: Props) {
  return <article className="min-w-0 rounded-xl border border-border bg-card p-4 shadow-sm sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="truncate text-base font-semibold">{strategy.name}</h3><span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted">{strategy.source || '内置策略'}</span></div>
        <p className="mt-1 text-sm leading-6 text-muted">{strategy.description || '暂无策略说明'}</p></div>
      <div className="flex shrink-0 gap-2"><button type="button" onClick={onDetails} className="rounded-lg border px-3 py-2 text-sm hover:bg-muted">详细说明</button><button type="button" onClick={onRun} className="rounded-lg bg-primary px-3 py-2 text-sm text-white">更新回测</button></div>
    </div>
    <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">{periods.map(([key, label]) => {
      const result = results[key]
      const unavailable = result && result.status !== 'completed'
      return <div key={key} className="rounded-lg bg-base p-3"><div className="flex items-center justify-between"><span className="text-xs text-muted">{label}</span><span className="text-xs text-muted">{result?.actual_end ?? '尚未回测'}</span></div>
        {unavailable ? <div className="mt-2 text-sm font-medium text-amber-600">不可用 · {result.reason || result.status}</div> : <div className="mt-2 grid grid-cols-3 gap-2">
          <Metric label="收益" value={percent(result?.total_return)} positive={result?.total_return != null && result.total_return >= 0} />
          <Metric label="最大回撤" value={percent(result?.max_drawdown)} />
          <Metric label="夏普" value={result?.sharpe == null ? '—' : result.sharpe.toFixed(2)} />
        </div>}
      </div>
    })}</div>
    <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3"><div className="flex flex-wrap gap-1.5">{(strategy.tags ?? []).slice(0, 5).map(tag => <span key={tag} className="rounded bg-muted px-2 py-1 text-xs text-muted">{tag}</span>)}<span className="text-xs text-muted">{strategy.asset_types?.join(' / ') || '—'} · {strategy.timeframes?.join(' / ') || '—'}</span></div>
      <label className="flex items-center gap-2 text-xs text-muted">手动分组<select aria-label={`放入分组 ${strategy.name}`} value={groupId} onChange={event => onGroup(event.target.value)} className="max-w-40 rounded-lg border bg-base px-2 py-1.5 text-sm text-foreground"><option value="">未分组</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label></div>
  </article>
}
function Metric({ label, value, positive }: { label: string; value: string; positive?: boolean }) { return <div><div className="text-[10px] text-muted">{label}</div><div className={`mt-0.5 text-sm font-semibold tabular-nums ${positive === undefined ? '' : positive ? 'text-emerald-600' : 'text-red-500'}`}>{value}</div></div> }
