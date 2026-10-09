// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { StrategyOptimizerPage } from './StrategyOptimizerPage'

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
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
    throw new Error(`unexpected request ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  await act(async () => root.render(<StrategyOptimizerPage />))
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
  expect(fetchMock).toHaveBeenCalledWith('/api/custom/strategy-optimizer/runs', expect.objectContaining({ method: 'POST' }))
})
