export type OptimizerStrategy = { strategy_id: string; name: string; optimizable: boolean; reason: string | null }
export type OptimizerRun = { run_id: string; state: string; config: Record<string, unknown>; result?: Record<string, unknown>; error?: string }
export type OptimizerParameter = { id: string; label: string; type: 'int' | 'float' | 'bool' | 'enum'; default: number | boolean | string; minimum?: number; maximum?: number; step?: number; options: unknown[]; optimizable: boolean; group?: string | null; description?: string }
export type OptimizerContract = { strategy_id: string; name: string; asset_type: string; parameters: OptimizerParameter[]; buy_signals: string[]; sell_signals: string[]; constraints?: Array<{ left: string; op: string; right: string | number | boolean }> }
export type EvaluationMode = 'legacy' | 'robust'
export type HoldoutStatus = 'not_applicable' | 'pending' | 'passed' | 'failed' | 'insufficient'
export type WindowPlan = { id: string; start: string; end: string; role: 'development' | 'holdout' | 'diagnostic' }
export type RobustPreview = {
  strategy_id: string
  time_plan: { development: WindowPlan[]; holdout: WindowPlan | null; diagnostics: WindowPlan[] }
  calendar_source: string
  calendar_coverage: { requested_start: string; requested_end: string; covered_start: string; covered_end: string; trading_dates: number }
  data_generation: string
  budgets: { main_candidates: number; neighbor_candidates: number; estimated_backtests: number }
  holdout_usage: 'used' | 'declared_unused' | 'unknown'
  warnings: string[]
  strategy_snapshot_available: boolean
  run_available: boolean
  run_blocker: string | null
}
export type RobustSegment = { window_id: string; annualized_return: number | null; max_drawdown: number | null; trade_count: number | null; baseline_delta: number | null; percentile: number | null; failures: string[] }
export type RobustRecommendation = { candidate_id: string; base_score: number; robust_score: number | null; stability: number | null; segments: RobustSegment[]; holdout_status: HoldoutStatus }

const json = async (url: string, init?: RequestInit) => {
  const response = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } })
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}
export const optimizerApi = {
  strategies: () => json('/api/custom/strategy-optimizer/strategies') as Promise<OptimizerStrategy[]>,
  contract: (id: string) => json(`/api/custom/strategy-optimizer/strategies/${id}/contract`) as Promise<OptimizerContract>,
  preview: (config: Record<string, unknown>) => json('/api/custom/strategy-optimizer/preview', { method: 'POST', body: JSON.stringify(config) }) as Promise<RobustPreview>,
  run: (config: Record<string, unknown>) => json('/api/custom/strategy-optimizer/runs', { method: 'POST', body: JSON.stringify(config) }) as Promise<OptimizerRun>,
  get: (id: string) => json(`/api/custom/strategy-optimizer/runs/${id}`) as Promise<OptimizerRun>,
  list: () => json('/api/custom/strategy-optimizer/runs') as Promise<OptimizerRun[]>,
  cancel: (id: string) => json(`/api/custom/strategy-optimizer/runs/${id}/cancel`, { method: 'POST' }) as Promise<OptimizerRun>,
  resume: (id: string) => json(`/api/custom/strategy-optimizer/runs/${id}/resume`, { method: 'POST' }) as Promise<OptimizerRun>,
  saveRecommendations: (id: string, rank?: number) => json(`/api/custom/strategy-optimizer/runs/${id}/save${rank ? `?rank=${rank}` : ''}`, { method: 'POST' }) as Promise<{ saved: Array<{ strategy_id: string; name: string; already_saved: boolean }>; errors: Array<{ rank: number; error: string }> }>,
  eventsUrl: (id: string) => `/api/custom/strategy-optimizer/runs/${id}/events`,
}
