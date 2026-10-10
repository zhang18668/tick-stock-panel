// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { StrategyLibraryPage } from './StrategyLibraryPage'
import type { StrategyLibrary } from './api'
import { StrategyCard } from './components/StrategyCard'
import { StrategyDetail } from './components/StrategyDetail'
import { BacktestJobPanel } from './components/BacktestJobPanel'

const { library, saveGroups, optimizerStrategies, navigateMock } = vi.hoisted(() => ({
  library: vi.fn(),
  saveGroups: vi.fn(),
  optimizerStrategies: vi.fn(),
  navigateMock: vi.fn(),
}))
vi.mock('./api', async importOriginal => ({
  ...await importOriginal<typeof import('./api')>(),
  strategyLibraryApi: { library, saveGroups, startJob: vi.fn(), getJob: vi.fn(), cancelJob: vi.fn(), retryJob: vi.fn() },
}))
vi.mock('../strategy-optimizer/api', async importOriginal => ({
  ...await importOriginal<typeof import('../strategy-optimizer/api')>(),
  optimizerApi: { strategies: optimizerStrategies },
}))
vi.mock('react-router-dom', async importOriginal => ({
  ...await importOriginal<typeof import('react-router-dom')>(),
  useNavigate: () => navigateMock,
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
  optimizerStrategies.mockResolvedValue([{ strategy_id: 'builtin_x', name: 'X 策略', optimizable: true, reason: null }])
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
  expect(select?.className).toContain('dark:[color-scheme:dark]')
  const groupFilter = host.querySelector<HTMLSelectElement>('select[aria-label="筛选分组"]')
  expect(groupFilter?.className).toContain('text-foreground')
  expect(groupFilter?.className).toContain('dark:[color-scheme:dark]')
  expect(groupFilter?.querySelector('option')?.className).toContain('bg-card')
  await act(async () => {
    if (!select) return
    select.value = 'g1'
    select.dispatchEvent(new Event('change', { bubbles: true }))
    await Promise.resolve()
  })
  expect(saveGroups.mock.calls[0]?.[0]).toEqual([{ id: 'g1', name: '强势', order: 0, strategy_ids: ['builtin_x'] }])
})

it('selects groups before selecting only optimizer-capable strategies', async () => {
  const data = sampleLibrary() as unknown as StrategyLibrary
  data.strategies.push({ ...data.strategies[0]!, id: 'builtin_y', name: 'Y 策略' })
  data.groups[0]!.strategy_ids = ['builtin_x', 'builtin_y']
  library.mockResolvedValue(data)
  optimizerStrategies.mockResolvedValue([
    { strategy_id: 'builtin_x', name: 'X 策略', optimizable: true, reason: null },
    { strategy_id: 'builtin_y', name: 'Y 策略', optimizable: false, reason: 'missing contract' },
  ])
  await act(async () => root.render(<QueryClientProvider client={client}><StrategyLibraryPage /></QueryClientProvider>))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
  const action = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('优化所选策略'))!
  expect(action.disabled).toBe(true)
  const group = host.querySelector<HTMLInputElement>('input[aria-label="选择优化分组 强势"]')!
  await act(async () => { group.click(); await Promise.resolve() })
  const eligible = host.querySelector<HTMLInputElement>('input[aria-label="选择优化策略 X 策略"]')!
  const ineligible = host.querySelector<HTMLInputElement>('input[aria-label="选择优化策略 Y 策略"]')!
  expect(ineligible.disabled).toBe(true)
  await act(async () => { eligible.click(); await Promise.resolve() })
  expect(action.disabled).toBe(false)
  expect(action.textContent).toContain('（1）')
  await act(async () => action.click())
  expect(navigateMock).toHaveBeenCalledWith('/strategy-optimizer', { state: { strategyIds: ['builtin_x'] } })
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
  expect(host.querySelector('table[aria-label="回测表现"] tbody tr:last-child')?.textContent ?? '').toContain('回测区间超过当前限制')
})

it('renders the strategy name as a visible heading instead of a placeholder-shaped chip', async () => {
  const strategy = { ...sampleLibrary().strategies[0], source: 'BUILTIN' } as unknown as import('./api').StrategySummary
  await act(async () => root.render(<StrategyCard strategy={strategy} groups={[]} groupId="" onGroup={() => undefined} onDetails={() => undefined} onRun={() => undefined} results={{}} />))
  const heading = host.querySelector('h3')
  expect(heading?.textContent).toBe('X 策略')
  expect(heading?.className).toContain('text-base')
  expect(host.querySelector('h3.rounded-full')).toBeNull()
})

it('uses readable source and tag chips and A-share colors for returns', async () => {
  const strategy = {
    ...sampleLibrary().strategies[0],
    source: 'builtin',
    tags: ['趋势策略'],
    asset_types: ['stock'],
    timeframes: ['1d'],
  } as unknown as import('./api').StrategySummary
  const result = (total_return: number) => ({
    period: '3m' as const, status: 'completed', actual_start: '2026-07-09', actual_end: '2026-10-09',
    total_return, max_drawdown: -0.05, sharpe: 1, win_rate: 0.5, profit_factor: 1.2,
    benchmark_return: null, excess_return: null, trade_count: 3, config_fingerprint: null,
    source_fingerprint: null, updated_at: null, reason: null,
  })
  await act(async () => root.render(<StrategyCard strategy={strategy} groups={[]} groupId="" onGroup={() => undefined} onDetails={() => undefined} onRun={() => undefined} results={{ '3m': result(-0.03), '6m': result(0.03) }} />))
  const chips = [...host.querySelectorAll('span')]
  expect(chips.find(node => node.textContent === 'builtin')?.className).toContain('bg-elevated')
  expect(chips.find(node => node.textContent === '趋势策略')?.className).toContain('bg-elevated')
  const table = host.querySelector<HTMLTableElement>('table[aria-label="回测表现"]')
  expect([...table!.querySelectorAll('thead th')].map(node => node.textContent)).toEqual(['周期', '数据日期', '收益', '最大回撤', '夏普', '胜率', '交易次数'])
  const rows = [...table!.querySelectorAll('tbody tr')]
  expect(rows).toHaveLength(3)
  expect(rows[0]?.textContent).toContain('近 3 个月')
  expect(rows[0]?.children[2]?.className).toContain('text-bear')
  expect(rows[0]?.textContent).toContain('-3.00%')
  expect(rows[0]?.children[5]?.textContent).toBe('+50.00%')
  expect(rows[0]?.children[6]?.textContent).toBe('3')
  expect(rows[1]?.children[2]?.className).toContain('text-bull')
  expect(rows[1]?.textContent).toContain('+3.00%')
  expect(rows[2]?.textContent).toContain('尚未回测')
})

it('keeps strategy detail content inside a viewport-sized scrollable dialog', async () => {
  const strategy = {
    ...sampleLibrary().strategies[0],
    rules: [],
    entry_signals: [],
    exit_signals: [],
    basic_filter: { long_filter_key: 'x'.repeat(180) },
    execution: {},
    params: [],
    params_defaults: {},
    scoring: {},
    scoring_directions: {},
    stop_loss: null,
    take_profit: null,
    trailing_stop: null,
    trailing_take_profit_activate: null,
    trailing_take_profit_drawdown: null,
    max_hold_days: null,
    source: 'BUILTIN',
  } as unknown as import('./api').StrategySummary
  await act(async () => root.render(<StrategyDetail strategy={strategy} results={{}} onClose={() => undefined} />))
  const dialog = host.querySelector<HTMLElement>('[role="dialog"]')
  expect(dialog?.className).toContain('max-h-[92dvh]')
  expect(dialog?.className).toContain('flex-col')
  expect(dialog?.querySelector('[data-dialog-content]')?.className).toContain('overflow-y-auto')
  expect(dialog?.querySelector('[data-dialog-content]')?.className).toContain('min-h-0')
  expect(host.querySelector('[data-dialog-content] .break-all')).toBeTruthy()
})

it('shows partial task progress and offers retry for failed periods', async () => {
  const retry = vi.fn()
  const item = { strategy_id: 'builtin_x', period: '3m' as const, window: { requested_start: '2026-07-08', requested_end: '2026-10-08', actual_start: null, actual_end: null, availability: 'available', reason: null }, attempts: 1, progress: null, reason: 'worker error', started_at: null, status: 'failed' }
  const job = { id: 'job-1', state: 'completed_with_errors', items: Array.from({ length: 6 }, (_, index) => ({ ...item, strategy_id: index < 5 ? `s${index}` : 'builtin_x', status: index < 5 ? 'completed' : 'failed' })), counts: { completed: 5, failed: 1 }, current_strategy_id: null, current_period: null, cancel_requested: false, updated_at: '2026-10-10T00:00:00Z', error: null }
  await act(async () => root.render(<BacktestJobPanel job={job} strategies={[]} onRunAll={() => undefined} onCancel={() => undefined} onRetry={retry} onRefresh={() => undefined} busy={false} />))
  expect(host.textContent).toContain('已完成 5 / 6')
  const retryButton = [...host.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes('重试失败项'))
  expect(retryButton).toBeTruthy()
  await act(async () => { retryButton?.click() })
  expect(retry).toHaveBeenCalledOnce()
})

it('shows the active backtest item progress instead of claiming the job is still starting', async () => {
  const item = {
    strategy_id: 'builtin_x', period: '12m' as const,
    window: { requested_start: '2025-10-08', requested_end: '2026-10-08', actual_start: '2025-10-08', actual_end: '2026-10-08', availability: 'available', reason: null },
    status: 'running', attempts: 1, progress: { day: 120, total: 240, date: '2026-06-01' }, reason: null,
    started_at: '2026-10-10T01:00:00+00:00',
  }
  const job = { id: 'job-1', state: 'running', items: [item], counts: { running: 1 }, current_strategy_id: 'builtin_x', current_period: '12m', cancel_requested: false, updated_at: '2026-10-10T00:00:00Z', error: null }
  await act(async () => root.render(<BacktestJobPanel job={job} strategies={sampleLibrary().strategies as unknown as import('./api').StrategySummary[]} onRunAll={() => undefined} onCancel={() => undefined} onRetry={() => undefined} onRefresh={() => undefined} busy />))
  expect(host.textContent).toContain('任务运行中')
  expect(host.textContent).toContain('120 / 240')
  expect(host.textContent).toContain('2026-06-01')
  expect(host.textContent).not.toContain('正在启动…')
})

it('reports cancel and refresh actions and uses explicit readable select colors', async () => {
  const onCancel = vi.fn().mockResolvedValue(undefined)
  const onRefresh = vi.fn().mockResolvedValue(undefined)
  const item = { strategy_id: 'builtin_x', period: '3m' as const, window: { requested_start: '2026-07-08', requested_end: '2026-10-08', actual_start: null, actual_end: null, availability: 'available', reason: null }, attempts: 1, progress: null, reason: null, started_at: null, status: 'running' }
  const job = { id: 'job-2', state: 'running', items: [item], counts: { running: 1 }, current_strategy_id: 'builtin_x', current_period: '3m', cancel_requested: false, updated_at: '2026-10-10T00:00:00Z', error: null }
  await act(async () => root.render(<><BacktestJobPanel job={job} strategies={sampleLibrary().strategies as unknown as import('./api').StrategySummary[]} onRunAll={() => undefined} onCancel={onCancel} onRetry={() => undefined} onRefresh={onRefresh} busy /></>))
  const cancelButton = [...host.querySelectorAll('button')].find(button => button.textContent === '取消任务')
  const refreshButton = [...host.querySelectorAll('button')].find(button => button.textContent === '立即刷新')
  expect(cancelButton?.className).toContain('text-foreground')
  expect(refreshButton?.className).toContain('text-foreground')
  await act(async () => { cancelButton?.click(); await Promise.resolve() })
  expect(onCancel).toHaveBeenCalledOnce()
  expect(host.textContent).toContain('取消请求已发送')
  await act(async () => { refreshButton?.click(); await Promise.resolve() })
  expect(onRefresh).toHaveBeenCalledOnce()
  expect(host.textContent).toContain('状态已刷新')
})
