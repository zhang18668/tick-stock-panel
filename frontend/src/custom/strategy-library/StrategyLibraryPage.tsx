import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, BookOpenCheck, RefreshCw, Search } from 'lucide-react'
import { QK } from '../../lib/queryKeys'
import { strategyLibraryApi, type StrategyGroup, type StrategyJob, type StrategyLibrary, type StrategySummary } from './api'
import { BacktestJobPanel } from './components/BacktestJobPanel'
import { StrategyCard } from './components/StrategyCard'
import { StrategyDetail } from './components/StrategyDetail'
import { StrategyGroups } from './components/StrategyGroups'

const active = (state?: string) => state === 'queued' || state === 'running'
export function StrategyLibraryPage() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: QK.strategyLibrary, queryFn: strategyLibraryApi.library, staleTime: 30_000 })
  const [job, setJob] = useState<StrategyJob | null>(null)
  const [selected, setSelected] = useState<StrategySummary | null>(null)
  const [search, setSearch] = useState('')
  const [filterGroup, setFilterGroup] = useState('all')
  const [error, setError] = useState('')
  useEffect(() => { if (!job?.id) return; let cancelled = false; const poll = async () => { try { const next = await strategyLibraryApi.getJob(job.id); if (cancelled) return; setJob(next); if (!active(next.state)) void client.invalidateQueries({ queryKey: QK.strategyLibrary }) } catch (reason) { if (!cancelled) setError(String(reason)) } }; if (active(job.state)) { const timer = window.setInterval(poll, 1800); return () => { cancelled = true; window.clearInterval(timer) } } }, [job?.id, job?.state, client])
  useEffect(() => { if (!job && query.data?.tasks.length) setJob(query.data.tasks.find(item => active(item.state)) ?? query.data.tasks[0]) }, [query.data, job])
  const groups = query.data?.groups ?? []
  const save = useMutation({ mutationFn: strategyLibraryApi.saveGroups, onSuccess: async () => { setError(''); await client.invalidateQueries({ queryKey: QK.strategyLibrary }) }, onError: reason => setError(String(reason)) })
  const run = async (strategyIds?: string[]) => { setError(''); try { const next = await strategyLibraryApi.startJob(strategyIds); setJob(next) } catch (reason) { setError(String(reason)) } }
  const filtered = useMemo(() => (query.data?.strategies ?? []).filter(strategy => {
    const textMatch = `${strategy.name} ${strategy.description} ${strategy.id} ${(strategy.tags ?? []).join(' ')}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())
    const currentGroup = groups.find(group => group.strategy_ids.includes(strategy.id))?.id ?? ''
    return textMatch && (filterGroup === 'all' || (filterGroup === 'ungrouped' ? !currentGroup : currentGroup === filterGroup))
  }).sort((a, b) => {
    const groupOrder = (id: string) => groups.find(group => group.strategy_ids.includes(id))?.order ?? groups.length
    return groupOrder(a.id) - groupOrder(b.id) || a.name.localeCompare(b.name, 'zh-CN')
  }), [query.data?.strategies, groups, search, filterGroup])
  const assign = (strategyId: string, groupId: string) => {
    const next = groups.map(group => ({ ...group, strategy_ids: group.strategy_ids.filter(id => id !== strategyId) }))
    if (groupId) { const destination = next.find(group => group.id === groupId); if (destination) destination.strategy_ids.push(strategyId) }
    save.mutate(next)
  }
  const refresh = async () => { if (!job) return; try { setJob(await strategyLibraryApi.getJob(job.id)); await client.invalidateQueries({ queryKey: QK.strategyLibrary }) } catch (reason) { setError(String(reason)) } }
  const cancel = async () => { if (!job) return; try { setJob(await strategyLibraryApi.cancelJob(job.id)) } catch (reason) { setError(String(reason)) } }
  const retry = async () => { if (!job) return; try { setJob(await strategyLibraryApi.retryJob(job.id)) } catch (reason) { setError(String(reason)) } }
  const moveGroups = (next: StrategyGroup[]) => save.mutate(next)
  if (query.isPending) return <main className="mx-auto max-w-7xl p-4 sm:p-6"><div className="animate-pulse rounded-xl border p-8 text-sm text-muted">正在加载策略库…</div></main>
  if (query.isError) return <main className="mx-auto max-w-4xl p-6"><div role="alert" className="rounded-xl border border-red-300 bg-card p-5"><h1 className="font-semibold">策略库暂时无法加载</h1><p className="mt-2 text-sm text-muted">{query.error.message}</p><button type="button" onClick={() => void query.refetch()} className="mt-4 rounded-lg border px-3 py-2 text-sm">重试</button></div></main>
  const data = query.data as StrategyLibrary
  return <main className="mx-auto max-w-7xl space-y-5 p-4 pb-12 sm:p-6">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><div className="flex items-center gap-2 text-primary"><BookOpenCheck size={18} /><span className="text-xs font-semibold uppercase tracking-widest">Strategy library</span></div><h1 className="mt-1 text-2xl font-semibold tracking-tight">策略库与回测对比</h1><p className="mt-1 text-sm text-muted">浏览内置策略、自己定义档位，并在统一截止日比较近期回测表现。</p></div><div className="rounded-lg border bg-card px-3 py-2 text-xs text-muted">最近交易日 <span className="ml-1 font-medium text-foreground">{data.latest_trading_day ?? '暂无数据'}</span></div></header>
    {error && <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-300 bg-card p-3 text-sm text-red-600"><AlertCircle size={16} className="mt-0.5 shrink-0" />{error}<button type="button" className="ml-auto" onClick={() => setError('')} aria-label="关闭错误提示">×</button></div>}
    <StrategyGroups groups={groups} onChange={moveGroups} />
    <BacktestJobPanel job={job} strategies={data.strategies} onRunAll={() => void run()} onCancel={() => void cancel()} onRetry={() => void retry()} onRefresh={() => void refresh()} busy={active(job?.state)} />
    <section><div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="font-semibold">策略表现</h2><p className="mt-1 text-xs text-muted">收益、回撤和夏普比率按后端回测结果展示；缺失数据保留为空。</p></div><div className="flex w-full flex-wrap gap-2 sm:w-auto"><label className="relative min-w-48 flex-1 sm:flex-none"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" /><input aria-label="搜索策略" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索策略" className="w-full rounded-lg border bg-card py-2 pl-9 pr-3 text-sm" /></label><select aria-label="筛选分组" value={filterGroup} onChange={event => setFilterGroup(event.target.value)} className="rounded-lg border bg-card px-3 py-2 text-sm"><option value="all">全部分组</option><option value="ungrouped">未分组</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select><button type="button" onClick={() => void query.refetch()} className="inline-flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm"><RefreshCw size={14} />刷新</button></div></div>
      {filtered.length ? <div className="mt-4 grid gap-3 xl:grid-cols-2">{filtered.map(strategy => <StrategyCard key={strategy.id} strategy={strategy} groups={groups} groupId={groups.find(group => group.strategy_ids.includes(strategy.id))?.id ?? ''} results={data.results[strategy.id] ?? {}} onGroup={groupId => assign(strategy.id, groupId)} onDetails={() => setSelected(strategy)} onRun={() => void run([strategy.id])} />)}</div> : <div className="mt-4 rounded-xl border border-dashed p-10 text-center"><p className="font-medium">{data.strategies.length ? '没有匹配的策略' : '暂未发现可用策略'}</p><p className="mt-1 text-sm text-muted">{data.strategies.length ? '试试其他搜索词或分组。' : '检查服务器上的策略源码和策略访问权限。'}</p></div>}</section>
    <footer className="text-xs text-muted">数据覆盖：{data.earliest_daily_date ?? '—'} 至 {data.latest_trading_day ?? '—'} · 更新会逐项执行，单项失败不会阻止其他策略。</footer>
    {selected && <StrategyDetail strategy={selected} results={data.results[selected.id] ?? {}} onClose={() => setSelected(null)} />}
  </main>
}
