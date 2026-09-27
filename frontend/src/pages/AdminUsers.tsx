import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { api } from '@/lib/api'

type Tab = 'overview' | 'users' | 'codes' | 'strategies' | 'ranking'

const fmtDate = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '长期有效'
const remaining = (value?: string | null) => {
  if (!value) return '长期有效'
  const seconds = Math.max(0, Math.floor((new Date(value).getTime() - Date.now()) / 1000))
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  return seconds ? `${days}天 ${hours}小时` : '已到期'
}
const editableDays = (value?: string | null) => value
  ? Math.max(1, Math.ceil((new Date(value).getTime() - Date.now()) / 86400000))
  : 30
const json = (value: unknown) => JSON.stringify(value, null, 2)

export function AdminUsers() {
  const [tab, setTab] = useState<Tab>('overview')
  const [days, setDays] = useState<Record<string, number>>({})
  const [selectedPlans, setSelectedPlans] = useState<Record<string, string>>({})
  const [planFeedback, setPlanFeedback] = useState<Record<string, { kind: 'success' | 'error'; message: string }>>({})
  const [detail, setDetail] = useState<unknown>(null)
  const [codeCount, setCodeCount] = useState(1)
  const [codePlan, setCodePlan] = useState('pro_monthly')
  const [codeDays, setCodeDays] = useState(30)
  const [codeExpires, setCodeExpires] = useState(30)
  const [generatedCodes, setGeneratedCodes] = useState<string[]>([])
  const [creditCodeCount, setCreditCodeCount] = useState(1)
  const [creditCodePoints, setCreditCodePoints] = useState(100)
  const [creditCodeExpires, setCreditCodeExpires] = useState(30)
  const [generatedCreditCodes, setGeneratedCreditCodes] = useState<string[]>([])
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: ['admin-users'], queryFn: () => api.adminUsers() })
  const plans = useQuery({ queryKey: ['billing-plans'], queryFn: api.billingPlans })
  const overview = useQuery({ queryKey: ['admin-overview'], queryFn: api.adminOverview })
  const strategies = useQuery({ queryKey: ['admin-strategies'], queryFn: api.adminStrategies })
  const ranking = useQuery({ queryKey: ['admin-strategy-ranking'], queryFn: api.adminStrategyRanking })
  const registrationCodes = useQuery({ queryKey: ['admin-registration-codes'], queryFn: api.adminRegistrationCodes })
  const creditCodes = useQuery({ queryKey: ['admin-credit-codes'], queryFn: api.adminCreditCodes })
  const refreshUsers = () => queryClient.invalidateQueries({ queryKey: ['admin-users'] })
  const updateUser = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: { role?: 'user' | 'admin'; status?: 'active' | 'disabled' } }) => api.adminUpdateUser(id, payload),
    onSuccess: refreshUsers,
  })
  const assignPlan = useMutation({
    mutationFn: ({ id, plan, validDays }: { id: string; plan: string; validDays: number }) => api.adminAssignPlan(id, plan, validDays),
    onSuccess: (_, { id }) => {
      setPlanFeedback(old => ({ ...old, [id]: { kind: 'success', message: '已保存' } }))
      refreshUsers()
    },
    onError: (error, { id }) => {
      setPlanFeedback(old => ({ ...old, [id]: { kind: 'error', message: error instanceof Error ? error.message : '保存失败' } }))
    },
  })
  const createCodes = useMutation({
    mutationFn: () => api.adminCreateRegistrationCodes({ count: codeCount, plan_code: codePlan, valid_days: codeDays, expires_in_days: codeExpires }),
    onSuccess: data => { setGeneratedCodes(data.codes); void queryClient.invalidateQueries({ queryKey: ['admin-registration-codes'] }) },
  })
  const revokeCode = useMutation({
    mutationFn: api.adminRevokeRegistrationCode,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['admin-registration-codes'] }),
  })
  const createCreditCodes = useMutation({
    mutationFn: () => api.adminCreateCreditCodes({ count: creditCodeCount, points: creditCodePoints, expires_in_days: creditCodeExpires }),
    onSuccess: data => { setGeneratedCreditCodes(data.codes); void queryClient.invalidateQueries({ queryKey: ['admin-credit-codes'] }) },
  })
  const revokeCreditCode = useMutation({
    mutationFn: api.adminRevokeCreditCode,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['admin-credit-codes'] }),
  })
  const tabs: Array<[Tab, string]> = [['overview', '运营总览'], ['users', '用户与套餐'], ['codes', '注册兑换码'], ['strategies', '全部策略'], ['ranking', '正收益排行']]
  const timeline = overview.data?.timeline ?? []
  const timelineOption = {
    color: ['#38bdf8', '#a78bfa', '#34d399'],
    tooltip: { trigger: 'axis' },
    legend: { data: ['新增用户', '新增策略', '回测次数'], textStyle: { color: '#94a3b8' } },
    grid: { left: 42, right: 18, top: 44, bottom: 32 },
    xAxis: { type: 'category', boundaryGap: false, data: timeline.map(item => item.date.slice(5)), axisLabel: { color: '#94a3b8' } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: 'rgba(148,163,184,.15)' } } },
    series: [
      { name: '新增用户', type: 'line', smooth: true, symbol: 'none', data: timeline.map(item => item.users) },
      { name: '新增策略', type: 'line', smooth: true, symbol: 'none', data: timeline.map(item => item.strategies) },
      { name: '回测次数', type: 'line', smooth: true, symbol: 'none', data: timeline.map(item => item.backtests) },
    ],
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      <div><h1 className="text-xl font-semibold text-foreground">管理员后台</h1><p className="mt-1 text-sm text-muted">用户注册、页面使用、订阅套餐及策略回测总览。</p></div>
      <div className="flex gap-2 border-b border-border">{tabs.map(([id, label]) => <button key={id} onClick={() => setTab(id)} className={`px-3 py-2 text-sm ${tab === id ? 'border-b-2 border-accent text-accent' : 'text-muted'}`}>{label}</button>)}</div>

      {tab === 'overview' && <>
        <div className="grid gap-3 sm:grid-cols-3">{Object.entries({ 注册用户: overview.data?.counts.users, 已建策略: overview.data?.counts.strategies, 回测次数: overview.data?.counts.backtests }).map(([label, value]) => <div key={label} className="rounded-lg border border-border bg-surface p-4"><div className="text-xs text-muted">{label}</div><div className="mt-2 text-2xl font-semibold">{value ?? '—'}</div></div>)}</div>
        <section className="rounded-lg border border-border bg-surface p-4"><div className="mb-2"><h2 className="font-medium">近 30 天运营趋势</h2><p className="mt-1 text-xs text-muted">每日新增用户、策略与回测次数</p></div>{overview.isLoading ? <div className="grid h-72 place-items-center text-sm text-muted">加载趋势数据…</div> : timeline.length ? <ReactECharts option={timelineOption} style={{ height: 288, width: '100%' }} notMerge lazyUpdate /> : <div className="grid h-72 place-items-center text-sm text-muted">暂无趋势数据</div>}</section>
        <section className="overflow-hidden rounded-lg border border-border bg-surface"><div className="p-4"><h2 className="font-medium">Top 用户</h2><p className="mt-1 text-xs text-muted">按累计页面访问次数排序</p></div><div className="overflow-x-auto"><table className="w-full text-sm"><thead className="border-y border-border text-left text-xs text-muted"><tr><th className="p-3">排名</th><th className="p-3">用户</th><th className="p-3 text-right">访问</th><th className="p-3 text-right">策略</th><th className="p-3 text-right">回测</th><th className="p-3">最近活跃</th></tr></thead><tbody>{(overview.data?.top_users ?? []).map((user, index) => <tr key={user.id} className="border-b border-border/60 last:border-0"><td className="p-3 font-semibold text-accent">#{index + 1}</td><td className="p-3"><div>{user.display_name || user.email}</div>{user.display_name && <div className="text-xs text-muted">{user.email}</div>}</td><td className="p-3 text-right font-medium">{user.page_views}</td><td className="p-3 text-right">{user.strategies}</td><td className="p-3 text-right">{user.backtests}</td><td className="p-3 text-muted">{fmtDate(user.last_active_at)}</td></tr>)}{!overview.isLoading && !overview.data?.top_users.length && <tr><td colSpan={6} className="p-6 text-center text-muted">暂无用户活跃记录</td></tr>}</tbody></table></div></section>
        <section className="rounded-lg border border-border bg-surface p-4"><h2 className="mb-3 font-medium">页面使用情况</h2><div className="space-y-2">{(overview.data?.pages ?? []).map(row => <div key={row.path} className="grid grid-cols-[1fr_auto_auto] gap-6 text-sm"><span className="font-mono">{row.path}</span><span>{row.views} 次</span><span className="text-muted">{row.users} 人</span></div>)}{!overview.data?.pages.length && <div className="text-sm text-muted">暂无访问记录</div>}</div></section>
      </>}

      {tab === 'users' && <div className="overflow-x-auto rounded-lg border border-border bg-surface"><table className="w-full text-sm"><thead className="border-b border-border text-left text-xs text-muted"><tr><th className="p-3">用户</th><th className="p-3">注册/登录</th><th className="p-3">角色</th><th className="p-3">状态</th><th className="p-3">当前套餐与倒计时</th><th className="p-3">配置套餐</th></tr></thead><tbody>{(users.data?.users ?? []).map(user => <tr key={user.id} className="border-b border-border/60 last:border-0">
        <td className="p-3"><div>{user.email}</div><div className="text-xs text-muted">{user.display_name || user.id}</div></td><td className="p-3 text-xs"><div>{fmtDate(user.created_at)}</div><div className="text-muted">最近：{fmtDate(user.last_login_at)}</div></td>
        <td className="p-3"><select className="rounded border border-border bg-base px-2 py-1" value={user.role} onChange={e => updateUser.mutate({ id: user.id, payload: { role: e.target.value as 'user' | 'admin' } })}><option value="user">用户</option><option value="admin">管理员</option></select></td>
        <td className="p-3"><select className="rounded border border-border bg-base px-2 py-1" value={user.status} onChange={e => updateUser.mutate({ id: user.id, payload: { status: e.target.value as 'active' | 'disabled' } })}><option value="active">正常</option><option value="disabled">禁用</option></select></td>
        <td className="p-3"><div>{user.subscription?.plan_name ?? '未分配'}</div><div className="text-xs text-muted">{remaining(user.subscription?.current_period_end)} · {fmtDate(user.subscription?.current_period_end)}</div></td>
        <td className="p-3"><div className="space-y-1.5"><div className="flex flex-wrap items-center gap-2"><select className="rounded border border-border bg-base px-2 py-1" value={selectedPlans[user.id] ?? user.subscription?.plan_code ?? ''} onChange={e => { setSelectedPlans(old => ({ ...old, [user.id]: e.target.value })); setPlanFeedback(old => { const next = { ...old }; delete next[user.id]; return next }) }}><option value="" disabled>选择套餐</option>{(plans.data?.plans ?? []).map(plan => <option key={plan.code} value={plan.code}>{plan.name}</option>)}</select><label className="flex items-center gap-1"><input type="number" min={1} max={3650} value={days[user.id] ?? editableDays(user.subscription?.current_period_end)} onChange={e => { setDays(old => ({ ...old, [user.id]: Number(e.target.value) })); setPlanFeedback(old => { const next = { ...old }; delete next[user.id]; return next }) }} className="w-20 rounded border border-border bg-base px-2 py-1" title="从现在起的有效天数" /><span className="text-xs text-muted">天</span></label><button type="button" className="rounded bg-accent px-3 py-1 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={assignPlan.isPending || !(selectedPlans[user.id] ?? user.subscription?.plan_code)} onClick={() => { const plan = selectedPlans[user.id] ?? user.subscription?.plan_code; if (plan) { setPlanFeedback(old => { const next = { ...old }; delete next[user.id]; return next }); assignPlan.mutate({ id: user.id, plan, validDays: days[user.id] ?? editableDays(user.subscription?.current_period_end) }) } }}>{assignPlan.isPending && assignPlan.variables?.id === user.id ? '保存中…' : '确认修改'}</button></div><div className="text-xs text-muted">有效期从现在起重新计算，可缩短或延长。</div>{planFeedback[user.id] && <div className={`text-xs ${planFeedback[user.id].kind === 'success' ? 'text-success' : 'text-red-500'}`}>{planFeedback[user.id].message}</div>}</div></td>
      </tr>)}</tbody></table></div>}

      {tab === 'codes' && <div className="space-y-4">
        <section className="rounded-lg border border-accent/30 bg-surface p-4"><h2 className="font-medium">生成积分兑换码</h2><p className="mt-1 text-xs text-muted">用户兑换后积分立即到账。兑换码只能使用一次，明文仅在生成后显示一次。</p><div className="mt-4 flex flex-wrap items-end gap-3">
          <label className="text-xs text-muted">数量<input type="number" min={1} max={100} value={creditCodeCount} onChange={e => setCreditCodeCount(Number(e.target.value))} className="mt-1 block w-24 rounded border border-border bg-base px-2 py-1.5 text-foreground" /></label>
          <label className="text-xs text-muted">每个兑换码积分<input type="number" min={1} max={1000000} value={creditCodePoints} onChange={e => setCreditCodePoints(Number(e.target.value))} className="mt-1 block w-36 rounded border border-border bg-base px-2 py-1.5 text-foreground" /></label>
          <label className="text-xs text-muted">兑换有效期（天）<input type="number" min={1} max={3650} value={creditCodeExpires} onChange={e => setCreditCodeExpires(Number(e.target.value))} className="mt-1 block w-28 rounded border border-border bg-base px-2 py-1.5 text-foreground" /></label>
          <button onClick={() => createCreditCodes.mutate()} disabled={createCreditCodes.isPending} className="rounded bg-accent px-4 py-2 text-sm text-white disabled:opacity-50">{createCreditCodes.isPending ? '生成中…' : '生成积分兑换码'}</button>
        </div>{createCreditCodes.isError && <div className="mt-3 text-sm text-red-500">{createCreditCodes.error instanceof Error ? createCreditCodes.error.message : '生成失败'}</div>}
        {generatedCreditCodes.length > 0 && <div className="mt-4 rounded border border-success/30 bg-success/5 p-3"><div className="mb-2 text-xs text-success">本次生成（仅显示一次）</div><pre className="select-all whitespace-pre-wrap font-mono text-sm">{generatedCreditCodes.join('\n')}</pre><button onClick={() => void navigator.clipboard.writeText(generatedCreditCodes.join('\n'))} className="mt-2 text-xs text-accent">复制全部</button></div>}</section>
        <div className="overflow-x-auto rounded-lg border border-border bg-surface"><table className="w-full text-sm"><thead className="border-b border-border text-left text-xs text-muted"><tr><th className="p-3">积分码</th><th className="p-3">积分</th><th className="p-3">状态</th><th className="p-3">兑换用户</th><th className="p-3">有效期</th><th className="p-3">操作</th></tr></thead><tbody>{(creditCodes.data?.codes ?? []).map(item => <tr key={item.id} className="border-b border-border/60"><td className="p-3 font-mono">{item.code_prefix}…</td><td className="p-3 font-semibold text-accent">{item.points}</td><td className="p-3">{item.status === 'active' ? '未使用' : item.status === 'redeemed' ? '已兑换' : '已作废'}</td><td className="p-3">{item.redeemed_by ?? '—'}</td><td className="p-3 text-xs">{fmtDate(item.expires_at)}</td><td className="p-3">{item.status === 'active' && <button onClick={() => revokeCreditCode.mutate(item.id)} className="text-red-400">作废</button>}</td></tr>)}</tbody></table></div>
        <section className="rounded-lg border border-border bg-surface p-4"><h2 className="font-medium">生成注册兑换码</h2><p className="mt-1 text-xs text-muted">明文兑换码只在生成后显示一次，请立即复制并通过群内私发给用户。</p><div className="mt-4 flex flex-wrap items-end gap-3">
          <label className="text-xs text-muted">数量<input type="number" min={1} max={100} value={codeCount} onChange={e => setCodeCount(Number(e.target.value))} className="mt-1 block w-24 rounded border border-border bg-base px-2 py-1.5 text-foreground" /></label>
          <label className="text-xs text-muted">套餐<select value={codePlan} onChange={e => setCodePlan(e.target.value)} className="mt-1 block rounded border border-border bg-base px-2 py-1.5 text-foreground">{(plans.data?.plans ?? []).filter(plan => plan.code !== 'trial').map(plan => <option key={plan.code} value={plan.code}>{plan.name}</option>)}</select></label>
          <label className="text-xs text-muted">开通天数<input type="number" min={1} max={3650} value={codeDays} onChange={e => setCodeDays(Number(e.target.value))} className="mt-1 block w-24 rounded border border-border bg-base px-2 py-1.5 text-foreground" /></label>
          <label className="text-xs text-muted">兑换有效期（天）<input type="number" min={1} max={3650} value={codeExpires} onChange={e => setCodeExpires(Number(e.target.value))} className="mt-1 block w-28 rounded border border-border bg-base px-2 py-1.5 text-foreground" /></label>
          <button onClick={() => createCodes.mutate()} disabled={createCodes.isPending} className="rounded bg-accent px-4 py-2 text-sm text-white disabled:opacity-50">{createCodes.isPending ? '生成中…' : '生成兑换码'}</button>
        </div>{createCodes.isError && <div className="mt-3 text-sm text-red-500">{createCodes.error instanceof Error ? createCodes.error.message : '生成失败'}</div>}
        {generatedCodes.length > 0 && <div className="mt-4 rounded border border-success/30 bg-success/5 p-3"><div className="mb-2 text-xs text-success">本次生成（仅显示一次）</div><pre className="select-all whitespace-pre-wrap font-mono text-sm">{generatedCodes.join('\n')}</pre><button onClick={() => void navigator.clipboard.writeText(generatedCodes.join('\n'))} className="mt-2 text-xs text-accent">复制全部</button></div>}</section>
        <div className="overflow-x-auto rounded-lg border border-border bg-surface"><table className="w-full text-sm"><thead className="border-b border-border text-left text-xs text-muted"><tr><th className="p-3">编号</th><th className="p-3">套餐</th><th className="p-3">开通时长</th><th className="p-3">状态</th><th className="p-3">兑换用户</th><th className="p-3">有效期</th><th className="p-3">操作</th></tr></thead><tbody>{(registrationCodes.data?.codes ?? []).map(item => <tr key={item.id} className="border-b border-border/60"><td className="p-3 font-mono">{item.code_prefix}…</td><td className="p-3">{item.plan_name}</td><td className="p-3">{item.valid_days} 天</td><td className="p-3">{item.status === 'active' ? '未使用' : item.status === 'redeemed' ? '已兑换' : '已作废'}</td><td className="p-3">{item.redeemed_by ?? '—'}</td><td className="p-3 text-xs">{fmtDate(item.expires_at)}</td><td className="p-3">{item.status === 'active' && <button onClick={() => revokeCode.mutate(item.id)} className="text-red-400">作废</button>}</td></tr>)}</tbody></table></div>
      </div>}

      {tab === 'strategies' && <div className="grid gap-3 md:grid-cols-2">{(strategies.data?.strategies ?? []).map(item => <button key={item.id} onClick={() => setDetail(item)} className="rounded-lg border border-border bg-surface p-4 text-left hover:border-accent/50"><div className="font-medium">{String(item.meta.name || item.strategy_id)}</div><div className="mt-1 text-xs text-muted">{item.owner.email} · {item.source} · {fmtDate(item.updated_at)}</div><div className="mt-2 font-mono text-xs text-muted">{item.strategy_id}</div></button>)}</div>}

      {tab === 'ranking' && <div className="overflow-x-auto rounded-lg border border-border bg-surface"><table className="w-full text-sm"><thead className="border-b border-border text-left text-xs text-muted"><tr><th className="p-3">排名</th><th className="p-3">策略</th><th className="p-3">创建者</th><th className="p-3">收益率</th><th className="p-3">时间</th><th className="p-3">详情</th></tr></thead><tbody>{(ranking.data?.ranking ?? []).map((item, index) => <tr key={`${item.owner.id}-${item.run_id}`} className="border-b border-border/60"><td className="p-3">#{index + 1}</td><td className="p-3">{item.strategy_id || item.run_type}</td><td className="p-3">{item.owner.email}</td><td className="p-3 font-semibold text-success">{(item.return_ratio * 100).toFixed(2)}%</td><td className="p-3 text-muted">{fmtDate(item.created_at)}</td><td className="p-3"><button className="text-accent" onClick={() => setDetail(item)}>参数与结果</button></td></tr>)}</tbody></table></div>}

      {detail !== null && <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={() => setDetail(null)}><div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-lg border border-border bg-surface p-5" onClick={e => e.stopPropagation()}><div className="mb-3 flex justify-between"><h2 className="font-medium">策略详情</h2><button onClick={() => setDetail(null)} className="text-muted">关闭</button></div><pre className="whitespace-pre-wrap break-all rounded bg-base p-4 text-xs">{json(detail)}</pre></div></div>}
    </div>
  )
}
