import type { StrategyJob, StrategySummary } from '../api'

const active = (state: string) => state === 'queued' || state === 'running'
export function BacktestJobPanel({ job, strategies, onRunAll, onCancel, onRetry, onRefresh, busy }: {
  job: StrategyJob | null
  strategies: StrategySummary[]
  onRunAll: () => void
  onCancel: () => void
  onRetry: () => void
  onRefresh: () => void
  busy: boolean
}) {
  const failures = job?.items.filter(item => item.status === 'failed').length ?? 0
  const completed = job?.items.filter(item => ['completed', 'unavailable', 'cancelled'].includes(item.status)).length ?? 0
  const total = job?.items.length ?? 0
  const percent = total ? Math.round(completed / total * 100) : 0
  return <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">回测数据更新</h2><p className="mt-1 text-xs text-muted">按 3、6、12 个月窗口依次更新；运行中的任务会自动刷新进度。</p></div><button type="button" onClick={onRunAll} disabled={busy || !strategies.length} className="rounded-lg bg-primary px-4 py-2 text-sm text-white disabled:opacity-40">{busy ? '正在启动…' : '更新全部策略'}</button></div>
    {!job ? <p className="mt-4 text-sm text-muted">尚无更新任务。也可以在策略卡片上单独更新。</p> : <div className="mt-4 rounded-lg bg-base p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><div className="text-sm font-medium">{stateLabel(job.state)}{job.current_strategy_id && <span className="ml-2 text-xs text-muted">{strategies.find(strategy => strategy.id === job.current_strategy_id)?.name ?? job.current_strategy_id} · {job.current_period}</span>}</div><div className="flex flex-wrap gap-2">{active(job.state) ? <button type="button" onClick={onCancel} className="rounded-lg border px-3 py-1.5 text-sm">取消任务</button> : null}{failures > 0 && !active(job.state) ? <button type="button" onClick={onRetry} className="rounded-lg border px-3 py-1.5 text-sm">重试失败项（{failures}）</button> : null}{active(job.state) ? <button type="button" onClick={onRefresh} className="rounded-lg border px-3 py-1.5 text-sm">立即刷新</button> : null}</div></div>
      {total > 0 && <><div className="mt-3 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percent}%` }} /></div><div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted"><span>已完成 {completed} / {total} 项（{percent}%）</span><span>成功 {job.counts?.completed ?? job.items.filter(item => item.status === 'completed').length} · 失败 {failures} · 不可用 {job.counts?.unavailable ?? job.items.filter(item => item.status === 'unavailable').length}</span></div></>}
      {job.error && <p role="alert" className="mt-3 text-sm text-red-500">{job.error}</p>}
      {failures > 0 && <details className="mt-3"><summary className="cursor-pointer text-xs text-muted">查看失败项</summary><ul className="mt-2 space-y-1 text-xs text-red-500">{job.items.filter(item => item.status === 'failed').map(item => <li key={`${item.strategy_id}-${item.period}`}>{strategies.find(strategy => strategy.id === item.strategy_id)?.name ?? item.strategy_id} · {item.period}：{item.reason}</li>)}</ul></details>}
    </div>}
  </section>
}
function stateLabel(state: string) { return ({ queued: '排队中', running: '正在回测', completed: '更新完成', completed_with_errors: '部分完成', cancelled: '已取消', failed: '任务失败', interrupted: '任务中断' } as Record<string, string>)[state] ?? state }
