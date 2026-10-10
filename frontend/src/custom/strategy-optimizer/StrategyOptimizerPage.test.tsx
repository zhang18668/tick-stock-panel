// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrategyOptimizerPage } from './StrategyOptimizerPage'

const { locationState } = vi.hoisted(() => ({ locationState: { current: null as unknown } }))
vi.mock('react-router-dom', async importOriginal => ({
  ...await importOriginal<typeof import('react-router-dom')>(),
  useLocation: () => ({ state: locationState.current }),
}))

let host: HTMLDivElement
let root: Root
let client: QueryClient

beforeEach(() => {
  locationState.current = null
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
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
      return Response.json({ run_id: 'run-1', state: 'succeeded', config: body, result: { top3: [{ score: 0.9, parameters: { window: 10 } }] } })
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
  const save = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('保存到策略库'))!
  await act(async () => { save.click(); await new Promise(resolve => setTimeout(resolve, 10)) })
  expect(fetchMock).toHaveBeenCalledWith('/api/custom/strategy-optimizer/runs/run-1/save', expect.objectContaining({ method: 'POST' }))
  expect(host.textContent).toContain('已保存 1 个策略：Demo-top1')
  expect(fetchMock).toHaveBeenCalledWith('/api/custom/strategy-optimizer/runs', expect.objectContaining({ method: 'POST' }))
})
