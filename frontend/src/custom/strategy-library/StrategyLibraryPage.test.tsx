// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { StrategyLibraryPage } from './StrategyLibraryPage'
import { StrategyCard } from './components/StrategyCard'
import { BacktestJobPanel } from './components/BacktestJobPanel'

const { library, saveGroups } = vi.hoisted(() => ({
  library: vi.fn(),
  saveGroups: vi.fn(),
}))
vi.mock('./api', async importOriginal => ({
  ...await importOriginal<typeof import('./api')>(),
  strategyLibraryApi: { library, saveGroups, startJob: vi.fn(), getJob: vi.fn(), cancelJob: vi.fn(), retryJob: vi.fn() },
}))

let host: HTMLDivElement
let root: Root
let client: QueryClient
const sampleLibrary = () => ({
  strategies: [{ id: 'builtin_x', name: 'X 策略', description: '说明', rules: [], execution: {},
    params: {}, scoring: {}, risk: {}, signals: { buy: [], sell: [] } }],
  groups: [{ id: 'g1', name: '强势', order: 0, strategy_ids: [] }], results: {}, tasks: [], latest_trading_day: '2026-10-08', earliest_daily_date: '2020-01-01',
})

beforeEach(() => {
  vi.clearAllMocks()
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  library.mockResolvedValue(sampleLibrary())
  saveGroups.mockResolvedValue({ groups: sampleLibrary().groups })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
})

afterEach(async () => {
  await act(async () => root.unmount())
  vi.unstubAllGlobals()
  host.remove()
})

it('moves a strategy only after the user selects a group', async () => {
  await act(async () => root.render(<QueryClientProvider client={client}><StrategyLibraryPage /></QueryClientProvider>))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
  const select = host.querySelector<HTMLSelectElement>('select[aria-label="放入分组 X 策略"]')
  expect(select).toBeTruthy()
  await act(async () => {
    if (!select) return
    select.value = 'g1'
    select.dispatchEvent(new Event('change', { bubbles: true }))
    await Promise.resolve()
  })
  expect(saveGroups.mock.calls[0]?.[0]).toEqual([{ id: 'g1', name: '强势', order: 0, strategy_ids: ['builtin_x'] }])
})

it('shows unavailable windows and explains why the backtest is missing', async () => {
  const data = sampleLibrary()
  const strategy = data.strategies[0] as unknown as import('./api').StrategySummary
  const unavailable = { period: '12m' as const, status: 'unavailable', reason: '回测区间超过当前限制', actual_start: null, actual_end: null,
    total_return: null, max_drawdown: null, sharpe: null, win_rate: null, profit_factor: null, benchmark_return: null, excess_return: null, trade_count: null, config_fingerprint: null, source_fingerprint: null, updated_at: null }
  await act(async () => root.render(<StrategyCard strategy={strategy} groups={[]} groupId="" onGroup={() => undefined} onDetails={() => undefined} onRun={() => undefined} results={{ '12m': unavailable }} />))
  expect(host.textContent).toContain('近一年')
  expect(host.textContent).toContain('不可用')
  expect(host.textContent).toContain('回测区间超过当前限制')
})

it('shows partial task progress and offers retry for failed periods', async () => {
  const retry = vi.fn()
  const item = { strategy_id: 'builtin_x', period: '3m' as const, window: { requested_start: '2026-07-08', requested_end: '2026-10-08', actual_start: null, actual_end: null, availability: 'available', reason: null }, attempts: 1, progress: null, reason: 'worker error', status: 'failed' }
  const job = { id: 'job-1', state: 'completed_with_errors', items: Array.from({ length: 6 }, (_, index) => ({ ...item, strategy_id: index < 5 ? `s${index}` : 'builtin_x', status: index < 5 ? 'completed' : 'failed' })), counts: { completed: 5, failed: 1 }, current_strategy_id: null, current_period: null, error: null }
  await act(async () => root.render(<BacktestJobPanel job={job} strategies={[]} onRunAll={() => undefined} onCancel={() => undefined} onRetry={retry} onRefresh={() => undefined} busy={false} />))
  expect(host.textContent).toContain('已完成 5 / 6')
  const retryButton = [...host.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes('重试失败项'))
  expect(retryButton).toBeTruthy()
  await act(async () => { retryButton?.click() })
  expect(retry).toHaveBeenCalledOnce()
})
