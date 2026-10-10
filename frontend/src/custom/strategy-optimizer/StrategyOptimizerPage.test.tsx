// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrategyOptimizerPage } from './StrategyOptimizerPage'

const { navigateMock, locationState } = vi.hoisted(() => ({ navigateMock: vi.fn(), locationState: { current: null as unknown } }))
vi.mock('react-router-dom', async importOriginal => ({
  ...await importOriginal<typeof import('react-router-dom')>(),
  useNavigate: () => navigateMock,
  useLocation: () => ({ state: locationState.current }),
}))

let host: HTMLDivElement
let root: Root
let client: QueryClient

beforeEach(() => {
  navigateMock.mockReset()
  locationState.current = null
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
})

afterEach(async () => {
  await act(async () => root.unmount())
  client.clear()
  vi.unstubAllGlobals()
  host.remove()
})

it('loads a strategy contract and sends bounded optimization configuration', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/strategies')) {
      return Response.json([{ strategy_id: 'demo', name: 'Demo', optimizable: true, reason: null }])
    }
    if (url.endsWith('/contract')) {
      return Response.json({
        strategy_id: 'demo', name: 'Demo', asset_type: 'stock',
        parameters: [{ id: 'window', label: 'Window', type: 'int', default: 10, minimum: 2, maximum: 30, step: 1, options: [], optimizable: true }],
        buy_signals: ['buy_a'], sell_signals: ['sell_a'],
      })
    }
    if (url.endsWith('/runs') && !init?.method) return Response.json([])
    if (url.endsWith('/runs') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body))
      expect(body.parameters.window).toEqual({ min: 2, max: 30, step: 1 })
      expect(body.max_rounds).toBe(10)
      return Response.json({ run_id: 'run-1', state: 'succeeded', config: body, result: { top3: [{ score: 0.9, parameters: { window: 10 }, oos_metrics: { oos_return: -0.0553508, max_oos_drawdown: 0.0154, win_rate: 0.4117, trade_count: 119, fold_metrics: [{ total_return: 0.0029, max_drawdown: -0.0141, win_rate: 0.6154, n_trades: 13 }, { total_return: -0.0139, max_drawdown: -0.0146, win_rate: 0.4545, n_trades: 11 }] } }] } })
    }
    if (url.endsWith('/run-1/save')) return Response.json({ saved: [{ strategy_id: 'custom_opt_run_top1', name: 'Demo-top1', already_saved: false }], errors: [] })
    throw new Error(`unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  await act(async () => root.render(<QueryClientProvider client={client}><StrategyOptimizerPage /></QueryClientProvider>))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)) })
  const select = host.querySelector('select')!
  await act(async () => {
    Object.defineProperty(select, 'value', { value: 'demo', configurable: true })
    select.dispatchEvent(new Event('change', { bubbles: true }))
    await new Promise(resolve => setTimeout(resolve, 10))
  })
  const start = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('启动优化'))!
  await act(async () => { start.click(); await new Promise(resolve => setTimeout(resolve, 10)) })
  expect(host.textContent).toContain('推荐 1')
  expect(host.textContent).toContain('样本外收益')
  expect(host.textContent).toContain('-5.54%')
  expect(host.textContent).toContain('41.17%')
  expect(host.textContent).toContain('119 笔')
  expect(host.textContent).toContain('Window')
  expect(host.textContent).toContain('逐折收益')
  expect(host.querySelector('[aria-label="第 2 折收益 -1.39%"]')).not.toBeNull()
  const load = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('载入回测'))!
  await act(async () => load.click())
  expect(navigateMock).toHaveBeenCalledWith('/backtest?tab=strategy', expect.objectContaining({
    state: expect.objectContaining({ loadCandidate: expect.objectContaining({
      name: '策略优化推荐 1',
      config: expect.objectContaining({ strategy_id: 'demo', params: { window: 10 }, start: '2022-01-01', end: expect.any(String), symbols: [] }),
    }) }),
  }))
  const save = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('保存到策略库'))!
  await act(async () => { save.click(); await new Promise(resolve => setTimeout(resolve, 10)) })
  expect(fetchMock).toHaveBeenCalledWith('/api/custom/strategy-optimizer/runs/run-1/save', expect.objectContaining({ method: 'POST' }))
  expect(host.textContent).toContain('已保存 1 个策略：Demo-top1')
  expect(fetchMock).toHaveBeenCalledWith('/api/custom/strategy-optimizer/runs', expect.objectContaining({ method: 'POST' }))
})

it('opens the latest completed run and shows its optimization window', async () => {
  const latest = {
    run_id: 'latest-run', state: 'succeeded',
    config: { strategy_id: 'demo', asset_type: 'stock', start: '2023-01-01', end: '2023-12-31' },
    result: { top3: [{ score: 0.7, parameters: { window: 12 }, oos_metrics: { oos_return: 0.12, max_oos_drawdown: 0.08, win_rate: 0.6, trade_count: 40, fold_metrics: [{ total_return: 0.12 }] } }] },
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/strategies')) return Response.json([{ strategy_id: 'demo', name: 'Demo', optimizable: true, reason: null }])
    if (url.endsWith('/contract')) return Response.json({
      strategy_id: 'demo', name: 'Demo', asset_type: 'stock',
      parameters: [{ id: 'window', label: 'Window', type: 'int', default: 10, minimum: 2, maximum: 30, step: 1, options: [], optimizable: true }],
      buy_signals: [], sell_signals: [],
    })
    if (url.endsWith('/runs')) return Response.json([latest])
    throw new Error(`unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  await act(async () => root.render(<QueryClientProvider client={client}><StrategyOptimizerPage /></QueryClientProvider>))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)) })
  expect(host.textContent).toContain('推荐 1')
  expect(host.textContent).toContain('优化区间：2023-01-01 至 2023-12-31')
  expect(host.textContent).toContain('Window')
})
