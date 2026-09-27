import { useEffect, useMemo, useState } from 'react'

export function useSubscriptionRemaining(periodEnd?: string | null) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return useMemo(() => {
    if (!periodEnd) return { expired: false, label: '长期有效', seconds: null }
    const seconds = Math.max(0, Math.floor((new Date(periodEnd).getTime() - now) / 1000))
    if (seconds <= 0) return { expired: true, label: '已到期', seconds: 0 }
    const days = Math.floor(seconds / 86400)
    const hours = Math.floor((seconds % 86400) / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const secs = seconds % 60
    const label = days > 0 ? `${days}天 ${hours}小时 ${minutes}分` : `${hours}小时 ${minutes}分 ${secs}秒`
    return { expired: false, label, seconds }
  }, [now, periodEnd])
}
