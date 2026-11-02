// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { ChanReviewPage } from './ChanReviewPage'

let host: HTMLDivElement
let root: ReturnType<typeof createRoot>
const clients: QueryClient[] = []
async function waitFor(check: () => void) {
  let error: unknown
  for (let i = 0; i < 100; i++) {
    await act(async () => { await new Promise(r => setTimeout(r, 10)) })
    try { check(); return } catch (e) { error = e }
  }
  throw error
}
const screen = {
  getByRole: (_: string, { name }: { name: string | RegExp }) => {
    const found = [...host.querySelectorAll('button')].find(b => typeof name === 'string' ? (b.getAttribute('aria-label') ?? b.textContent) === name : name.test(b.getAttribute('aria-label') ?? b.textContent ?? ''))
    if (!found) throw new Error(`Missing button ${name}`)
    return found
  },
  async findByRole(role: string, options: { name: string | RegExp }) { await waitFor(() => { screen.getByRole(role, options) }); return screen.getByRole(role, options) },
  queryByTestId: (id: string) => host.querySelector(`[data-testid="${id}"]`),
  getByTestId: (id: string) => { const e = screen.queryByTestId(id); if (!e) throw new Error(id); return e },
  async findByTestId(id: string) { await waitFor(() => { screen.getByTestId(id) }); return screen.getByTestId(id) },
  getByText: (text: string | RegExp) => { if (typeof text === 'string' ? !host.textContent?.includes(text) : !text.test(host.textContent ?? '')) throw new Error(String(text)); return host },
  async findByText(text: string | RegExp) { await waitFor(() => { screen.getByText(text) }); return host },
  getByLabelText: (text: string) => { const el = host.querySelector<HTMLInputElement>(`[aria-label="${text}"]`); if (!el) throw new Error(text); return el },
}
const fireEvent = {
  click: (el: HTMLElement) => act(() => el.click()),
  change: (el: HTMLInputElement, { target }: { target: { value: string } }) => act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, target.value)
    el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }))
  }),
}

vi.mock('@/components/EChartsCandlestick', () => ({ EChartsCandlestick: ({ data, structureLines = [] }: any) =>
  <div data-testid="chart">{data.map((r: any) => r.date).join(',')}<span data-testid="line-count">{structureLines.length}</span></div> }))

const item = { id: 'a', symbol: '600000.SH', name: '浦发银行', category: '1', point_type: '1p', source: 'backfill', period: 'day',
  first_seen: '2025-03-03', last_seen: '2025-03-05', point_date: '2025-03-01', point_price: 10, snapshot_id: 'snap-a',
  structure_id: 'signal-a', status: 'observed', left_censored: true, engine_revision: 'revision', config_hash: 'config' }
const row = (date: string) => ({ date, open: 10, high: 12, low: 9, close: 11, volume: 100 })
const snapshot = { snapshot_id: 'snap-a', symbol: item.symbol, period: 'day', rows: [row('2025-03-01'), row('2025-03-03')],
  structures: [], observed_as_of: '2025-03-03', warnings: [], engine: { name: 'chan.py', revision: 'revision', config: {} } }
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  act(() => root.render(<QueryClientProvider client={client}><ChanReviewPage /></QueryClientProvider>)); clients.push(client)
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); host = document.createElement("div"); document.body.append(host); root = createRoot(host)
  vi.spyOn(api, 'chanReviewSignals').mockResolvedValue({ items: [item], counts: { '1': 1, '2': 0, '3': 0 }, total: 1, page: 1, page_size: 30 } as any)
  vi.spyOn(api, 'chanReviewRuns').mockResolvedValue({ items: [] })
  vi.spyOn(api, 'chanReviewSnapshot').mockResolvedValue(snapshot as any)
  vi.spyOn(api, 'chanReviewSignal').mockResolvedValue({ ...item, observations: [] } as any)
  vi.spyOn(api, 'chanReviewFollowing').mockResolvedValue({ symbol: item.symbol, period: 'day', rows: [...snapshot.rows, row('2025-03-04'), row('2025-03-05')] } as any)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); clients.splice(0).forEach(c => c.clear()); vi.restoreAllMocks() })

it('展示分类历史并默认只显示归档时可见的K线，后续按根展开', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /浦发银行/ }))
  await screen.findByTestId('chart')
  expect(screen.getByTestId('chart').textContent).not.toContain('2025-03-04')
  expect(api.chanReviewFollowing).not.toHaveBeenCalled()
  expect(screen.getByText(/窗口开始前已存在/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '后续走势' }))
  await waitFor(() => expect(api.chanReviewFollowing).toHaveBeenCalled())
  expect(screen.getByTestId('chart').textContent).not.toContain('2025-03-04')
  fireEvent.click(screen.getByRole('button', { name: '下一根' }))
  expect(screen.getByTestId('chart').textContent).toContain('2025-03-04')
  expect(screen.getByTestId('chart').textContent).not.toContain('2025-03-05')
  expect(screen.getByTestId('line-count').textContent).toBe('0')
})

it('切换分类清空旧图，空档案给出创建任务入口', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /浦发银行/ }))
  await screen.findByTestId('chart')
  vi.mocked(api.chanReviewSignals).mockResolvedValue({ items: [], total: 0, counts: { '1': 0, '2': 0, '3': 0 }, page: 1, page_size: 30 })
  fireEvent.click(screen.getByRole('button', { name: /3买/ }))
  await screen.findByText('暂无已归档信号')
  expect(screen.queryByTestId('chart')).toBeNull()
  expect(screen.getByRole('button', { name: '新建扫描' })).toBeTruthy()
})

it('提交后台补算任务并显示进度，可取消当前任务', async () => {
  vi.spyOn(api, 'chanReviewCreate').mockResolvedValue({ run_id: 'run1', status: 'queued' } as any)
  vi.spyOn(api, 'chanReviewCancel').mockResolvedValue({ run_id: 'run1', status: 'cancelling' } as any)
  mount()
  fireEvent.click(screen.getByRole('button', { name: '新建扫描' }))
  fireEvent.change(screen.getByLabelText('扫描起始日期'), { target: { value: '2025-03-01' } })
  fireEvent.change(screen.getByLabelText('扫描结束日期'), { target: { value: '2025-03-05' } })
  vi.mocked(api.chanReviewRuns).mockResolvedValue({ items: [{ run_id: 'run1', status: 'running', request: { source: 'backfill', start: '2025-03-01', end: '2025-03-05', period: 'day' }, summary: { planned: 100, processed: 12, completed: 12 }, created_at: '' } as any] })
  fireEvent.click(screen.getByRole('button', { name: '开始扫描' }))
  await waitFor(() => expect(api.chanReviewCreate).toHaveBeenCalledWith(expect.objectContaining({ source: 'backfill', start: '2025-03-01', end: '2025-03-05' })))
  await screen.findByText(/12 \/ 100/)
  fireEvent.click(screen.getByRole('button', { name: '取消任务' }))
  await waitFor(() => expect(api.chanReviewCancel).toHaveBeenCalledWith('run1'))
})

it('翻页后可按同一分类继续下一只，列表失败可重试', async () => {
  const next = { ...item, id: 'b', symbol: '000001.SZ', name: '平安银行', snapshot_id: 'snap-b' }
  vi.mocked(api.chanReviewSignals).mockImplementation(async filters => ({ items: filters.page === 1 ? [item] : [next], total: 31, counts: { '1': 31, '2': 0, '3': 0 }, page: filters.page, page_size: 30 } as any))
  vi.mocked(api.chanReviewSnapshot).mockImplementation(async id => ({ ...snapshot, snapshot_id: id, symbol: id === 'snap-b' ? next.symbol : item.symbol } as any))
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /浦发银行/ }))
  await screen.findByTestId('chart')
  fireEvent.click(screen.getByRole('button', { name: '下一只' }))
  await waitFor(() => expect(api.chanReviewSnapshot).toHaveBeenCalledWith('snap-b', expect.anything()))
  await screen.findByTestId('chart')
  expect(host.textContent).toContain('平安银行')
  vi.mocked(api.chanReviewSignals).mockRejectedValueOnce(new Error('archive unavailable'))
  fireEvent.click(screen.getByRole('button', { name: /2买/ }))
  await screen.findByText('加载失败')
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await screen.findByRole('button', { name: /浦发银行/ })
})

it('切股清理播放计时器并回到原图', async () => {
  const next = { ...item, id: 'b', symbol: '000001.SZ', name: '平安银行', snapshot_id: 'snap-b' }
  vi.mocked(api.chanReviewSignals).mockResolvedValue({ items: [item, next], total: 2, counts: { '1': 2, '2': 0, '3': 0 }, page: 1, page_size: 30 } as any)
  vi.mocked(api.chanReviewSnapshot).mockImplementation(async id => ({ ...snapshot, snapshot_id: id, symbol: id === 'snap-b' ? next.symbol : item.symbol } as any))
  const clear = vi.spyOn(window, 'clearInterval')
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /浦发银行/ }))
  await screen.findByTestId('chart')
  fireEvent.click(screen.getByRole('button', { name: '后续走势' }))
  await waitFor(() => expect(api.chanReviewFollowing).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('button', { name: '播放' }))
  await screen.findByRole('button', { name: '暂停' })
  fireEvent.click(screen.getByRole('button', { name: /平安银行/ }))
  await screen.findByTestId('chart')
  expect(clear).toHaveBeenCalled()
  expect(screen.queryByTestId('chart')?.textContent).not.toContain('2025-03-04')
  expect(host.querySelector('button[aria-pressed="true"]')?.textContent).toContain('1买')
})

it('切股后旧后续慢响应不能覆盖新股原图', async () => {
  const next = { ...item, id: 'b', symbol: '000001.SZ', name: '平安银行', snapshot_id: 'snap-b' }
  vi.mocked(api.chanReviewSignals).mockResolvedValue({ items: [item, next], total: 2, counts: { '1': 2, '2': 0, '3': 0 }, page: 1, page_size: 30 } as any)
  vi.mocked(api.chanReviewSnapshot).mockImplementation(async id => ({ ...snapshot, snapshot_id: id, symbol: id === 'snap-b' ? next.symbol : item.symbol } as any))
  let resolve!: (data: any) => void
  vi.mocked(api.chanReviewFollowing).mockImplementationOnce(() => new Promise(done => { resolve = done }))
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /浦发银行/ }))
  await screen.findByTestId('chart')
  fireEvent.click(screen.getByRole('button', { name: '后续走势' }))
  await waitFor(() => expect(resolve).toBeTypeOf('function'))
  fireEvent.click(screen.getByRole('button', { name: /平安银行/ }))
  await screen.findByTestId('chart')
  await act(async () => resolve({ symbol: item.symbol, period: 'day', rows: [...snapshot.rows, row('2025-03-04')] }))
  expect(screen.getByTestId('chart').textContent).not.toContain('2025-03-04')
  expect(host.textContent).toContain('平安银行 · 000001.SZ')
})
