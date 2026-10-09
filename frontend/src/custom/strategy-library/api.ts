export type StrategySummary = {
  id: string
  name: string
  description: string
  rules: unknown[]
  execution: Record<string, unknown>
  tags: string[]
  source: string
  params: Array<Record<string, unknown>>
  params_defaults: Record<string, unknown>
  scoring: Record<string, unknown>
  scoring_directions: Record<string, string>
  entry_signals: string[]
  exit_signals: string[]
  basic_filter: unknown
  stop_loss: number | null
  take_profit: number | null
  trailing_stop: number | null
  trailing_take_profit_activate: number | null
  trailing_take_profit_drawdown: number | null
  max_hold_days: number | null
  execution_backend: string
  asset_types: string[]
  timeframes: string[]
}
export type StrategyGroup = { id: string; name: string; order: number; strategy_ids: string[] }
export type StrategyResult = {
  period: '3m' | '6m' | '12m'
  actual_start: string | null
  actual_end: string | null
  status: string
  reason: string | null
  total_return: number | null
  max_drawdown: number | null
  sharpe: number | null
  win_rate: number | null
  profit_factor: number | null
  benchmark_return: number | null
  excess_return: number | null
  trade_count: number | null
  config_fingerprint: string | null
  source_fingerprint: string | null
  updated_at: string | null
}
export type JobItem = {
  strategy_id: string
  period: '3m' | '6m' | '12m'
  window: { requested_start: string; requested_end: string; actual_start: string | null; actual_end: string | null; availability: string; reason: string | null }
  status: string
  attempts: number
  progress: Record<string, unknown> | null
  reason: string | null
}
export type StrategyJob = {
  id: string
  state: string
  items: JobItem[]
  counts: Record<string, number>
  current_strategy_id: string | null
  current_period: string | null
  error: string | null
}
export type StrategyLibrary = {
  strategies: StrategySummary[]
  groups: StrategyGroup[]
  results: Record<string, Partial<Record<'3m' | '6m' | '12m', StrategyResult>>>
  tasks: StrategyJob[]
  latest_trading_day: string | null
  earliest_daily_date: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    let message = await response.text()
    try {
      const parsed = JSON.parse(message) as { detail?: unknown }
      message = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail ?? parsed)
    } catch { /* Keep the response body as the error. */ }
    throw new Error(message || `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const strategyLibraryApi = {
  library: () => request<StrategyLibrary>('/api/strategy-library'),
  saveGroups: (groups: StrategyGroup[]) => request<{ groups: StrategyGroup[] }>('/api/strategy-library/groups', {
    method: 'PUT', body: JSON.stringify({ groups }),
  }),
  startJob: (strategyIds?: string[]) => request<StrategyJob>('/api/strategy-library/jobs', {
    method: 'POST', body: JSON.stringify(strategyIds ? { strategy_ids: strategyIds } : {}),
  }),
  getJob: (id: string) => request<StrategyJob>(`/api/strategy-library/jobs/${encodeURIComponent(id)}`),
  cancelJob: (id: string) => request<StrategyJob>(`/api/strategy-library/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => request<StrategyJob>(`/api/strategy-library/jobs/${encodeURIComponent(id)}/retry`, {
    method: 'POST', body: JSON.stringify({}),
  }),
}
