// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CustomStrategyBacktestPage } from './CustomStrategyBacktestPage'

const { library, forwarded } = vi.hoisted(() => ({ library: vi.fn(), forwarded: vi.fn() }))
vi.mock('./api', async importOriginal => ({
  ...await importOriginal<typeof import('./api')>(),
  strategyLibraryApi: { library },
}))
vi.mock('../../pages/backtest/StrategyBacktest', () => ({
  StrategyBacktest: (props: Record<string, unknown>) => {
    forwarded(props)
    const groups = props.libraryGroups as Array<{ id: string; name: string }> | undefined
    return <div data-testid="backtest">{groups?.map(group => group.name).join(',')}</div>
  },
}))

let host: HTMLDivElement
let root: Root
let client: QueryClient

beforeEach(() => {
  vi.clearAllMocks()
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
})

it('passes library groups into the shared backtest page', async () => {
  library.mockResolvedValue({ groups: [{ id: 'g1', name: '趋势', order: 0, strategy_ids: ['s1'] }] })
  await act(async () => root.render(<QueryClientProvider client={client}><CustomStrategyBacktestPage /></QueryClientProvider>))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })

  expect(host.textContent).toContain('自定义策略')
  expect(host.querySelector('[data-testid="backtest"]')?.textContent).toContain('趋势')
  expect(forwarded.mock.calls.at(-1)?.[0]).toMatchObject({ strategyGroupingMode: 'library', libraryGroupsLoading: false })
})

it('keeps the shared backtest mounted and exposes retry after a library error', async () => {
  library.mockRejectedValue(new Error('服务暂不可用'))
  await act(async () => root.render(<QueryClientProvider client={client}><CustomStrategyBacktestPage /></QueryClientProvider>))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })

  expect(host.querySelector('[data-testid="backtest"]')).toBeTruthy()
  expect(forwarded.mock.calls.at(-1)?.[0]).toMatchObject({ strategyGroupingMode: 'library', libraryGroupsError: '服务暂不可用' })
  expect(typeof forwarded.mock.calls.at(-1)?.[0].onRetryLibraryGroups).toBe('function')
})
