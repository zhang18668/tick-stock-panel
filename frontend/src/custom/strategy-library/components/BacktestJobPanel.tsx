import { useEffect, useState } from 'react'
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
  const [now, setNow] = useState(() => Date.now())
  const [action, setAction] = useState<'cancel' | 'refresh' | null>(null)
  const [feedback, setFeedback] = useState('')
  useEffect(() => {
    if (!active(job?.state)) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [job?.state])
  const failures = job?.items.filter(item => item.status === 'failed').length ?? 0
  const completed = job?.items.filter(item => ['completed', 'unavailable', 'cancelled'].includes(item.status)).length ?? 0
  const total = job?.items.length ?? 0
  const percent = total ? Math.round(completed / total * 100) : 0
  const currentItem = job?.items.find(item => item.strategy_id === job.current_strategy_id && item.period === job.current_period)
  const runtime = currentItem?.started_at ? formatRuntime(now - Date.parse(currentItem.started_at)) : null
  const perform = async (kind: 'cancel' | 'refresh', callback: () => void | Promise<void>) => {
    setAction(kind)
    setFeedback('')
    try {
      await callback()
      setFeedback(kind === 'cancel' ? '取消请求已发送，等待当前回测停止。' : `状态已刷新 · ${new Date().toLocaleTimeString()}`)
    } catch (error) {
      setFeedback(`${kind === 'cancel' ? '取消失败' : '刷新失败'}：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setAction(null)
    }
  }
  return <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">回测数据更新</h2><p className="mt-1 text-xs text-muted">按 3、6、12 个月窗口依次更新；运行中的任务会自动刷新进度。</p></div><button type="button" onClick={onRunAll} disabled={busy || !strategies.length} className="rounded-lg bg-primary px-4 py-2 text-sm text-white disabled:opacity-40">{job?.state === 'running' ? '任务运行中' : job?.state === 'queued' ? '任务排队中' : '更新全部策略'}</button></div>
    {!job ? <p className="mt-4 text-sm text-muted">尚无更新任务。也可以在策略卡片上单独更新。</p> : <div className="mt-4 rounded-lg bg-base p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><div className="text-sm font-medium">{stateLabel(job.state)}{job.current_strategy_id && <span className="ml-2 text-xs text-muted">{strategies.find(strategy => strategy.id === job.current_strategy_id)?.name ?? job.current_strategy_id} · {job.current_period}</span>}</div><div className="flex flex-wrap gap-2">{active(job.state) && !job.cancel_requested ? <button type="button" disabled={action !== null} onClick={() => void perform('cancel', onCancel)} className="rounded-lg border px-3 py-1.5 text-sm text-foreground hover:bg-elevated disabled:opacity-50">{action === 'cancel' ? '正在取消…' : '取消任务'}</button> : null}{failures > 0 && !active(job.state) ? <button type="button" onClick={onRetry} className="rounded-lg border px-3 py-1.5 text-sm text-foreground hover:bg-elevated">重试失败项（{failures}）</button> : null}{active(job.state) ? <button type="button" disabled={action !== null} onClick={() => void perform('refresh', onRefresh)} className="rounded-lg border px-3 py-1.5 text-sm text-foreground hover:bg-elevated disabled:opacity-50">{action === 'refresh' ? '刷新中…' : '立即刷新'}</button> : null}</div></div>
      {job.cancel_requested && active(job.state) && <p role="status" className="mt-2 text-xs text-warning">取消请求已提交，正在等待当前回测安全停止…</p>}
      {feedback && <p role="status" className={`mt-2 text-xs ${feedback.includes('失败') ? 'text-danger' : 'text-secondary'}`}>{feedback}</p>}
      {job.state === 'running' && currentItem && <div aria-live="polite" className="mt-2 text-xs text-secondary">{currentItem.progress ? progressLabel(currentItem.progress) : '正在准备回测数据或计算信号，准备阶段暂不提供百分比进度。'}{runtime && <span className="ml-2 text-muted">当前项已运行 {runtime}</span>}</div>}
      {total > 0 && <><div className="mt-3 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percent}%` }} /></div><div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted"><span>已完成 {completed} / {total} 项（{percent}%）</span><span>成功 {job.counts?.completed ?? job.items.filter(item => item.status === 'completed').length} · 失败 {failures} · 不可用 {job.counts?.unavailable ?? job.items.filter(item => item.status === 'unavailable').length}</span></div></>}
      {job.error && <p role="alert" className="mt-3 text-sm text-red-500">{job.error}</p>}
      {failures > 0 && <details className="mt-3"><summary className="cursor-pointer text-xs text-muted">查看失败项</summary><ul className="mt-2 space-y-1 text-xs text-red-500">{job.items.filter(item => item.status === 'failed').map(item => <li key={`${item.strategy_id}-${item.period}`}>{strategies.find(strategy => strategy.id === item.strategy_id)?.name ?? item.strategy_id} · {item.period}：{item.reason}</li>)}</ul></details>}
    </div>}
  </section>
}
function stateLabel(state: string) { return ({ queued: '排队中', running: '正在回测', completed: '更新完成', completed_with_errors: '部分完成', cancelled: '已取消', failed: '任务失败', interrupted: '任务中断' } as Record<string, string>)[state] ?? state }
function progressLabel(progress: Record<string, unknown>) {
  const day = typeof progress.day === 'number' ? progress.day : null
  const total = typeof progress.total === 'number' ? progress.total : null
  const date = typeof progress.date === 'string' ? progress.date : null
  if (day != null && total != null) return `回测计算中：第 ${day} / ${total} 个交易日${date ? ` · ${date}` : ''}`
  if (typeof progress.label === 'string') return progress.label
  return typeof progress.phase === 'string' ? `回测阶段：${progress.phase}` : '回测计算中…'
}
function formatRuntime(milliseconds: number) {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return null
  const seconds = Math.floor(milliseconds / 1000)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  return hours ? `${hours}小时${minutes}分` : minutes ? `${minutes}分${remainder}秒` : `${remainder}秒`
}
