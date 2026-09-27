import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useSubscriptionRemaining } from '@/lib/subscription'
import feishuGroup from '@/assets/feishu-group.png'

export function Subscription() {
  const client = useQueryClient()
  const plans = useQuery({ queryKey: ['billing-plans'], queryFn: api.billingPlans })
  const current = useQuery({ queryKey: ['billing-me'], queryFn: api.billingMe })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [registrationCode, setRegistrationCode] = useState('')
  const [redeemSuccess, setRedeemSuccess] = useState('')
  const [creditCode, setCreditCode] = useState('')
  const remaining = useSubscriptionRemaining(current.data?.subscription?.current_period_end)
  const isExpiredTrial = current.data?.effective_plan === 'expired'
    && current.data?.subscription?.plan?.code === 'trial'

  const buyWithCredits = async (code: 'pro_monthly' | 'pro_yearly') => {
    setBusy(true); setError('')
    try { await api.purchaseWithCredits(code); await client.invalidateQueries({ queryKey: ['billing-me'] }) }
    catch (e) { setError(e instanceof Error ? e.message : '积分购买失败') }
    finally { setBusy(false) }
  }

  const redeemCode = async () => {
    const code = registrationCode.trim()
    if (!code) return
    setBusy(true); setError(''); setRedeemSuccess('')
    try {
      await api.redeemRegistrationCode(code)
      setRegistrationCode('')
      setRedeemSuccess('兑换成功，套餐有效期已更新。')
      await client.invalidateQueries({ queryKey: ['billing-me'] })
    } catch (e) { setError(e instanceof Error ? e.message : '兑换失败') }
    finally { setBusy(false) }
  }

  const redeemCreditCode = async () => {
    const code = creditCode.trim()
    if (!code) return
    setBusy(true); setError(''); setRedeemSuccess('')
    try {
      const result = await api.redeemCreditCode(code)
      setCreditCode('')
      setRedeemSuccess(`兑换成功，${result.points} 积分已到账。`)
      await client.invalidateQueries({ queryKey: ['billing-me'] })
    } catch (e) { setError(e instanceof Error ? e.message : '积分兑换失败') }
    finally { setBusy(false) }
  }

  const paidPlans = plans.data?.plans.filter(p => p.code.startsWith('pro_')) ?? []
  const redemptionSection = current.data?.effective_plan === 'expired' && <section className="rounded-card border border-accent/30 bg-elevated p-5">
    <h2 className="font-medium">使用兑换码开通</h2>
    <p className="mt-1 text-xs text-muted">输入管理员提供的一次性兑换码，兑换后立即恢复对应套餐。</p>
    <div className="mt-4 flex flex-col gap-2 sm:flex-row">
      <input value={registrationCode} onChange={e => setRegistrationCode(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') void redeemCode() }} placeholder="请输入兑换码" autoComplete="off" className="min-w-0 flex-1 rounded-btn border border-border bg-base px-3 py-2 text-sm" />
      <button type="button" disabled={busy || !registrationCode.trim()} onClick={() => void redeemCode()} className="rounded-btn bg-accent px-5 py-2 text-sm text-white disabled:opacity-40">{busy ? '兑换中…' : '立即兑换'}</button>
    </div>
    {redeemSuccess && <div className="mt-3 text-sm text-success">{redeemSuccess}</div>}
  </section>
  return <div className="mx-auto max-w-4xl space-y-6 p-6">
    {redemptionSection}
    <div><h1 className="text-xl font-semibold">订阅专业版</h1>
      <p className="mt-1 text-sm text-muted">当前套餐：{current.data?.effective_plan === 'trial' ? '试用版' : current.data?.effective_plan?.startsWith('pro_') ? '专业版' : current.data?.effective_plan === 'expired' ? '已到期' : '加载中'}</p>
      {current.data?.subscription && <p className={`mt-1 text-sm ${remaining.expired ? 'text-danger' : 'text-accent'}`}>剩余时间：{remaining.label}</p>}
      {current.data?.effective_plan === 'expired' && !isExpiredTrial && <p className="mt-3 rounded-btn bg-warning/10 p-3 text-sm text-warning">订阅已经到期。开通专业版后即可继续访问系统功能。</p>}
    </div>
    {current.data?.credits && <section className="rounded-card border border-border bg-elevated p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><div className="text-sm text-muted">可用积分</div><div className="mt-1 text-3xl font-semibold">{(current.data.credits.balance_cents / 100).toFixed(2)}</div><div className="mt-1 text-xs text-muted">1 积分抵扣 ¥1，仅限购买平台服务</div><div className="mt-4 flex max-w-sm gap-2"><input value={creditCode} onChange={e => setCreditCode(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') void redeemCreditCode() }} placeholder="输入积分兑换码" autoComplete="off" className="min-w-0 flex-1 rounded-btn border border-border bg-base px-3 py-2 text-sm" /><button disabled={busy || !creditCode.trim()} onClick={() => void redeemCreditCode()} className="rounded-btn bg-accent px-4 py-2 text-sm text-white disabled:opacity-40">兑换积分</button></div></div><div className="min-w-[260px]"><div className="text-sm font-medium">邀请好友，得 50% 积分奖励</div><div className="mt-1 text-xs text-muted">好友通过推荐地址注册并完成付费后，实付金额的一半转为积分。</div><div className="mt-3 flex gap-2"><input readOnly value={`${window.location.origin}/login?ref=${current.data.credits.referral_code}`} className="min-w-0 flex-1 rounded-btn border border-border bg-base px-3 py-2 text-xs"/><button onClick={() => void navigator.clipboard.writeText(`${window.location.origin}/login?ref=${current.data?.credits.referral_code}`)} className="rounded-btn border border-accent px-3 py-2 text-xs text-accent">复制</button></div><div className="mt-2 text-xs text-muted">已推荐 {current.data.credits.referred_users} 人 · 推荐码 {current.data.credits.referral_code}</div></div></div>{redeemSuccess && <div className="mt-3 text-sm text-success">{redeemSuccess}</div>}</section>}
    {isExpiredTrial && <section className="rounded-card border border-warning/30 bg-warning/5 p-5">
      <div className="text-center">
        <h2 className="text-lg font-semibold text-foreground">试用期已结束</h2>
        <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-secondary">
          加入晨风复盘工作台飞书群，可免费领取注册码和积分兑换码，兑换后即可继续使用。
        </p>
      </div>
      <div className="mx-auto mt-5 max-w-md">
        <div className="rounded-card border border-border bg-white p-3 text-center shadow-sm">
          <img src={feishuGroup} alt="晨风复盘工作台飞书群二维码" className="mx-auto w-full max-w-[360px] object-contain" />
          <div className="mt-3 text-sm font-medium text-gray-900">加入晨风复盘工作台飞书群</div>
          <div className="mt-1 text-xs text-gray-500">进群可免费领取注册码和积分兑换码</div>
        </div>
      </div>
    </section>}
    <div className="grid gap-4 md:grid-cols-2">{paidPlans.map(plan => <div key={plan.code} className="rounded-card border border-border bg-elevated p-5">
      <div className="text-lg font-medium">{plan.name}</div><div className="my-4 text-3xl font-semibold">¥{(plan.price_cents / 100).toFixed(0)}<span className="text-sm text-muted">/{plan.billing_period === 'year' ? '年' : '月'}</span></div>
      <button disabled={busy || (current.data?.credits.balance_cents ?? 0) < plan.price_cents} onClick={() => void buyWithCredits(plan.code as 'pro_monthly' | 'pro_yearly')}
        className="w-full rounded-btn border border-accent px-4 py-2 text-sm text-accent disabled:opacity-40">使用 {plan.price_cents / 100} 积分购买</button>
    </div>)}</div>
    {error && <div className="rounded-btn bg-danger/10 p-3 text-sm text-danger">{error}</div>}
  </div>
}
