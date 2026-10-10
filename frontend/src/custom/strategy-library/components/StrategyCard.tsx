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
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="min-w-0 text-base font-semibold leading-6 text-foreground [overflow-wrap:anywhere]">{strategy.name?.trim() || '未命名策略'}</h3><span className="rounded-full bg-elevated px-2 py-0.5 text-[11px] text-secondary">{strategy.source || '内置策略'}</span></div>
        <p className="mt-1 text-sm leading-6 text-secondary">{strategy.description || '暂无策略说明'}</p></div>
      <div className="flex shrink-0 gap-2"><button type="button" onClick={onDetails} className="rounded-lg border px-3 py-2 text-sm hover:bg-muted">详细说明</button><button type="button" onClick={onRun} className="rounded-lg bg-primary px-3 py-2 text-sm text-white">更新回测</button></div>
    </div>
    <div className="mt-4 overflow-x-auto">
      <table aria-label="回测表现" className="w-full min-w-[560px] table-fixed border-collapse text-xs">
        <thead><tr className="border-b border-border text-secondary"><th scope="col" className="w-[19%] px-2 py-1.5 text-left font-medium">周期</th><th scope="col" className="w-[19%] px-2 py-1.5 text-left font-medium">数据日期</th><th scope="col" className="w-[13%] px-2 py-1.5 text-right font-medium">收益</th><th scope="col" className="w-[16%] px-2 py-1.5 text-right font-medium">最大回撤</th><th scope="col" className="w-[11%] px-2 py-1.5 text-right font-medium">夏普</th><th scope="col" className="w-[11%] px-2 py-1.5 text-right font-medium">胜率</th><th scope="col" className="w-[11%] px-2 py-1.5 text-right font-medium">交易次数</th></tr></thead>
        <tbody>{periods.map(([key, label]) => {
          const result = results[key]
          const unavailable = result && result.status !== 'completed'
          return <tr key={key} className="border-b border-border/60 last:border-0">
            <th scope="row" className="whitespace-nowrap px-2 py-2 text-left font-medium text-foreground">{label}</th>
            <td className="whitespace-nowrap px-2 py-2 text-secondary">{result?.actual_end ?? '尚未回测'}</td>
            {unavailable ? <td colSpan={5} className="px-2 py-2 text-right font-medium text-amber-600">不可用 · {result.reason || result.status}</td> : <>
              <td className={`whitespace-nowrap px-2 py-2 text-right font-semibold tabular-nums ${result?.total_return == null ? 'text-secondary' : result.total_return >= 0 ? 'text-bull' : 'text-bear'}`}>{percent(result?.total_return)}</td>
              <td className="whitespace-nowrap px-2 py-2 text-right font-semibold tabular-nums text-foreground">{percent(result?.max_drawdown)}</td>
              <td className="whitespace-nowrap px-2 py-2 text-right font-semibold tabular-nums text-foreground">{result?.sharpe == null ? '—' : result.sharpe.toFixed(2)}</td>
              <td className="whitespace-nowrap px-2 py-2 text-right font-semibold tabular-nums text-foreground">{percent(result?.win_rate)}</td>
              <td className="whitespace-nowrap px-2 py-2 text-right font-semibold tabular-nums text-foreground">{result?.trade_count ?? '—'}</td>
            </>}
          </tr>
        })}</tbody>
      </table>
    </div>
    <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3"><div className="flex flex-wrap gap-1.5">{(strategy.tags ?? []).slice(0, 5).map(tag => <span key={tag} className="rounded bg-elevated px-2 py-1 text-xs text-secondary">{tag}</span>)}<span className="text-xs text-secondary">{strategy.asset_types?.join(' / ') || '—'} · {strategy.timeframes?.join(' / ') || '—'}</span></div>
      <label className="flex items-center gap-2 text-xs text-secondary">手动分组<select aria-label={`放入分组 ${strategy.name}`} value={groupId} onChange={event => onGroup(event.target.value)} className="max-w-40 rounded-lg border bg-base px-2 py-1.5 text-sm text-foreground dark:[color-scheme:dark]"><option className="bg-card text-foreground" value="">未分组</option>{groups.map(group => <option className="bg-card text-foreground" key={group.id} value={group.id}>{group.name}</option>)}</select></label></div>
  </article>
}
