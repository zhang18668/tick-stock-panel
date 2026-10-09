export type OptimizerStrategy = { strategy_id: string; name: string; optimizable: boolean; reason: string | null }
export type OptimizerRun = { run_id: string; state: string; config: Record<string, unknown>; result?: Record<string, unknown>; error?: string }
export type OptimizerParameter = { id: string; label: string; type: 'int' | 'float' | 'bool' | 'enum'; default: number | boolean | string; minimum?: number; maximum?: number; step?: number; options: unknown[]; optimizable: boolean; group?: string | null; description?: string }
export type OptimizerContract = { strategy_id: string; name: string; asset_type: string; parameters: OptimizerParameter[]; buy_signals: string[]; sell_signals: string[]; constraints?: Array<{ left: string; op: string; right: string | number | boolean }> }

const json = async (url: string, init?: RequestInit) => {
  const response = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } })
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}
export const optimizerApi = {
  strategies: () => json('/api/custom/strategy-optimizer/strategies') as Promise<OptimizerStrategy[]>,
  contract: (id: string) => json(`/api/custom/strategy-optimizer/strategies/${id}/contract`) as Promise<OptimizerContract>,
  run: (config: Record<string, unknown>) => json('/api/custom/strategy-optimizer/runs', { method: 'POST', body: JSON.stringify(config) }) as Promise<OptimizerRun>,
  get: (id: string) => json(`/api/custom/strategy-optimizer/runs/${id}`) as Promise<OptimizerRun>,
  list: () => json('/api/custom/strategy-optimizer/runs') as Promise<OptimizerRun[]>,
  cancel: (id: string) => json(`/api/custom/strategy-optimizer/runs/${id}/cancel`, { method: 'POST' }) as Promise<OptimizerRun>,
  resume: (id: string) => json(`/api/custom/strategy-optimizer/runs/${id}/resume`, { method: 'POST' }) as Promise<OptimizerRun>,
  eventsUrl: (id: string) => `/api/custom/strategy-optimizer/runs/${id}/events`,
}
