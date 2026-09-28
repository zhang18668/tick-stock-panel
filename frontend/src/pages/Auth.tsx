import { useEffect, useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Eye, EyeOff, Loader2, Lock, ShieldAlert, ShieldCheck, Sparkles } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { Logo } from '@/components/Logo'
import feishuGroup from '@/assets/feishu-group.png'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

type AuthMode = 'standalone' | 'multi_user'

interface BootstrapState {
  mode: AuthMode
  configured: boolean
}

export function Auth() {
  const navigate = useNavigate()
  const [bootstrap, setBootstrap] = useState<BootstrapState | null>(null)
  const [registering, setRegistering] = useState(false)
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [registrationCode, setRegistrationCode] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [localError, setLocalError] = useState('')
  const referralCode = new URLSearchParams(window.location.search).get('ref') || ''

  useEffect(() => {
    let active = true
    void api.authMode()
      .then(async ({ mode }) => {
        if (mode === 'multi_user') {
          const status = await api.accountStatus()
          if (!active) return
          if (status.authenticated) {
            navigateRedirect(navigate)
            return
          }
          setBootstrap({ mode, configured: true })
          return
        }
        const status = await api.authStatus()
        if (!active) return
        if (status.authenticated) {
          navigateRedirect(navigate)
          return
        }
        setBootstrap({ mode, configured: status.configured })
      })
      .catch((error: Error) => {
        if (active) setLocalError(error.message || '无法获取认证状态')
      })
    return () => { active = false }
  }, [navigate])

  const isMultiUser = bootstrap?.mode === 'multi_user'
  const isStandaloneSetup = bootstrap?.mode === 'standalone' && !bootstrap.configured

  const submitMutation = useMutation({
    mutationFn: async () => {
      if (isMultiUser) {
        return registering
          ? api.accountRegister(email.trim(), password, displayName.trim(), referralCode, registrationCode.trim())
          : api.accountLogin(email.trim(), password)
      }
      return isStandaloneSetup ? api.authSetup(password) : api.authLogin(password)
    },
    onSuccess: () => navigateRedirect(navigate),
    onError: (error: Error) => setLocalError(error.message || '认证失败'),
  })

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    setLocalError('')
    if (isMultiUser && !email.trim()) {
      setLocalError('请输入邮箱')
      return
    }
    if (isMultiUser && registering && !displayName.trim()) {
      setLocalError('请输入昵称')
      return
    }
    const minimum = isMultiUser ? 8 : 6
    if (password.length < minimum) {
      setLocalError(`密码至少 ${minimum} 位`)
      return
    }
    if ((registering || isStandaloneSetup) && password !== confirmPassword) {
      setLocalError('两次输入的密码不一致')
      return
    }
    submitMutation.mutate()
  }

  if (!bootstrap && !localError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base">
        <Loader2 className="h-6 w-6 animate-spin text-muted" />
      </div>
    )
  }

  const title = isMultiUser
    ? (registering ? '创建账号' : '登录晨风复盘工作台')
    : (isStandaloneSetup ? '设置访问密码' : '登录访问')
  const subtitle = isMultiUser
    ? (registering ? '创建你的个人量化工作空间' : '使用邮箱和密码继续')
    : (isStandaloneSetup ? '首次使用，请为面板设置访问密码' : '请输入访问密码以继续')

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-x-hidden bg-base px-4 py-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(139,92,246,0.15),transparent_40%),radial-gradient(circle_at_70%_80%,rgba(59,130,246,0.12),transparent_40%)]" />
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="relative w-full max-w-sm"
      >
        <div className="mb-6 flex flex-col items-center">
          <div className="grid h-14 w-14 place-items-center rounded-2xl border border-purple-400/20 bg-purple-500/10 shadow-[0_0_32px_rgba(139,92,246,0.16)]">
            <Logo className="h-9 w-9 text-purple-400" />
          </div>
          <h1 className="mt-3 text-lg font-semibold tracking-[0.12em] text-foreground">晨风复盘工作台</h1>
          <p className="mt-1 font-mono text-[9px] uppercase tracking-[0.24em] text-muted">Quant Terminal</p>
        </div>

        <div className="rounded-card border border-border bg-surface/90 p-6 shadow-2xl backdrop-blur">
          <div className="mb-5 flex items-center gap-2.5">
            <div className={cn(
              'grid h-9 w-9 place-items-center rounded-lg',
              registering || isStandaloneSetup
                ? 'bg-accent/15 text-accent'
                : 'bg-purple-500/15 text-purple-400',
            )}>
              {registering || isStandaloneSetup
                ? <ShieldCheck className="h-5 w-5" />
                : <Lock className="h-5 w-5" />}
            </div>
            <div>
              <div className="text-sm font-medium text-foreground">{title}</div>
              <div className="text-[11px] text-muted">{subtitle}</div>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            {isMultiUser && (
              <input
                type="email"
                value={email}
                onChange={event => setEmail(event.target.value)}
                placeholder="邮箱"
                autoComplete="email"
                autoFocus
                className={inputClass}
              />
            )}
            {isMultiUser && registering && (
              <><input
                value={displayName}
                onChange={event => setDisplayName(event.target.value)}
                placeholder="昵称（必填）"
                autoComplete="name"
                className={inputClass}
              />{referralCode && <div className="rounded-btn bg-accent/10 px-3 py-2 text-xs text-accent">推荐码 {referralCode} 已应用。</div>}
              <details className="group rounded-btn border border-accent/30 bg-accent/5 px-3 py-2.5">
                <summary className="cursor-pointer list-none text-xs font-medium text-accent marker:content-none">
                  还没有兑换码？先扫码加入飞书群
                  <span className="float-right transition-transform group-open:rotate-180">⌄</span>
                </summary>
                <div className="pt-3 text-center">
                  <img
                    src={feishuGroup}
                    alt="晨风复盘工作台飞书群二维码"
                    className="mx-auto w-full max-w-[220px] rounded-btn bg-white object-contain p-2"
                  />
                  <ol className="mt-3 space-y-1 text-left text-[11px] leading-relaxed text-muted">
                    <li>1. 使用飞书扫描上方二维码加入群聊</li>
                    <li>2. 进群后领取注册兑换码</li>
                    <li>3. 返回此页，将兑换码填入下方输入框</li>
                  </ol>
                </div>
              </details>
              <input
                value={registrationCode}
                onChange={event => setRegistrationCode(event.target.value.toUpperCase())}
                placeholder="群内兑换码（必填）"
                autoComplete="off"
                className={inputClass}
              />
              <div className="text-[11px] leading-relaxed text-muted">注册码需先加入飞书群领取；注册成功后还可在群内领取积分兑换码。</div></>
            )}
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={event => setPassword(event.target.value)}
                placeholder={isMultiUser ? '密码（至少 8 位）' : '访问密码'}
                autoComplete={registering || isStandaloneSetup ? 'new-password' : 'current-password'}
                autoFocus={!isMultiUser}
                className={`${inputClass} pr-9`}
              />
              <button
                type="button"
                onClick={() => setShowPassword(value => !value)}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted hover:text-foreground"
                tabIndex={-1}
                aria-label={showPassword ? '隐藏密码' : '显示密码'}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            {(registering || isStandaloneSetup) && (
              <input
                type={showPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={event => setConfirmPassword(event.target.value)}
                placeholder="再次输入密码"
                autoComplete="new-password"
                className={inputClass}
              />
            )}

            {localError && (
              <div className="flex items-start gap-1.5 rounded-btn bg-danger/10 px-3 py-2 text-[11px] text-danger">
                <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0" />
                <span>{localError}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={submitMutation.isPending || !password || (isMultiUser && !email.trim())}
              className="inline-flex h-10 w-full items-center justify-center gap-1.5 rounded-btn bg-accent text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
            >
              {submitMutation.isPending
                ? <><Loader2 className="h-4 w-4 animate-spin" />处理中…</>
                : (registering ? '注册并进入' : isStandaloneSetup ? '设置并进入' : '登录')}
            </button>
          </form>

          {isMultiUser && (
            <button
              type="button"
              onClick={() => {
                setRegistering(value => !value)
                setConfirmPassword('')
                setLocalError('')
              }}
              className="mt-4 w-full text-center text-xs text-accent hover:underline"
            >
              {registering ? '已有账号？返回登录' : '没有账号？立即注册'}
            </button>
          )}
        </div>

        <div className="mt-4 flex items-center justify-center gap-1.5 text-[10px] text-muted/60">
          <Sparkles className="h-3 w-3" />
          行情全平台共享 · 用户数据独立保存
        </div>
      </motion.div>
    </div>
  )
}

const inputClass = 'h-10 w-full rounded-btn border border-border bg-base px-3 text-sm text-foreground outline-none transition-colors focus:border-accent/50'

function navigateRedirect(navigate: ReturnType<typeof useNavigate>) {
  const redirect = new URLSearchParams(window.location.search).get('redirect') || '/'
  navigate(redirect, { replace: true })
}
