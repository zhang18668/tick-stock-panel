// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ChanAnalysisPage } from './ChanAnalysisPage'
import { api, type KlineDailyResponse, type ChanAnalysisResponse } from '@/lib/api'

vi.mock('@/components/financials/StockFinancialSearch', () => ({
  StockFinancialSearch: ({ onSelect }: { onSelect: (s: string, n: string) => void }) => <div>
    <button onClick={() => onSelect('600000.SH', '浦发银行')}>选择浦发银行</button>
    <button onClick={() => onSelect('000001.SZ', '平安银行')}>选择平安银行</button>
  </div>,
}))
// Canvas has no layout engine in jsdom; preserve its boundary contract.
vi.mock('@/components/EChartsCandlestick', () => ({
  EChartsCandlestick: ({ data, symbol, structureLines, ranges, focusRange }: any) => <output aria-label="K线绘图数据">{JSON.stringify({ data, symbol, structureLines, ranges, focusRange })}</output>,
}))

let host: HTMLDivElement
let root: ReturnType<typeof createRoot>
let client: QueryClient
const response = (symbol = '600000.SH'): KlineDailyResponse => ({ symbol, name: symbol === '600000.SH' ? '浦发银行' : '平安银行', source: 'local', rows: [5, 7, 6, 5, 4, 3, 4, 5, 6, 8, 7, 6, 5, 2, 3, 4, 5, 9, 8].map((v, i) => ({ date: `2026-01-${String(i + 1).padStart(2, '0')}`, open: v, high: v + 1, low: v, close: v + 1, volume: 10 })) })
const analysisResponse = (symbol: string, period: 'day' | 'week', rows: any[]): ChanAnalysisResponse => ({
  symbol, period, rows: period === 'week' ? [rows[0], rows.at(-1)] : rows,
  structures: rows.length >= 11 ? [{ id: 'stroke:one', kind: 'stroke', start: { date: '2026-01-02', price: 8, index: 1 }, end: { date: '2026-01-06', price: 3, index: 5 }, confirmedAt: '2026-01-11', observedAt: rows.at(-1).date, label: '下行笔', basis: 'chan.py fixture' }] : [],
  asOf: rows.at(-1)?.date ?? null, ruleVersion: 'chan.py · strict / chan / normal',
  warnings: period === 'week' ? ['最后一周保守视为未完成'] : [],
  engine: { name: 'chan.py', revision: 'f8ca3b5e44d7166e2abd756a8e7fa816c79faebe', config: {} },
})
async function flush() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)) }) }
async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find(b => b.textContent?.includes(text))
  expect(button, text).toBeTruthy()
  await act(async () => button!.click())
  await flush()
}
function plotted() { return JSON.parse(host.querySelector('output')!.textContent!) }
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  vi.spyOn(api, 'klineDaily').mockResolvedValue(response())
  vi.spyOn(api, 'chanAnalyze').mockImplementation(async (symbol, period, rows) => analysisResponse(symbol, period, rows))
  await act(async () => root.render(<QueryClientProvider client={client}><ChanAnalysisPage /></QueryClientProvider>))
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); client.clear(); vi.restoreAllMocks() })

it('选择股票后显示真实价格和结构，图层开关移除结构线', async () => {
  expect(host.textContent).toContain('输入股票代码')
  expect(host.querySelector('output')).toBeNull()
  await click('选择浦发银行')
  await flush()
  expect(host.textContent).toContain('浦发银行')
  expect(plotted().symbol).toBe('600000.SH')
  expect(plotted().structureLines.length).toBeGreaterThan(0)
  await click('笔 ')
  expect(plotted().structureLines.every((l: any) => !l.id.startsWith('stroke:'))).toBe(true)
})

it('加载失败可重试，空行情显示缺失提示', async () => {
  vi.mocked(api.klineDaily).mockRejectedValueOnce(new Error('数据源不可用'))
  await click('选择浦发银行')
  await flush()
  expect(host.textContent).toContain('加载失败')
  vi.mocked(api.klineDaily).mockResolvedValueOnce({ ...response(), rows: [] })
  await click('重试')
  expect(host.textContent).toContain('暂无K线数据')
  expect(host.querySelector('output')).toBeNull()
})

it('切股时清除旧图，旧响应不覆盖新股票', async () => {
  let resolveB!: (value: KlineDailyResponse) => void
  await click('选择浦发银行')
  vi.mocked(api.klineDaily).mockImplementationOnce(() => new Promise(resolve => { resolveB = resolve }))
  await click('选择平安银行')
  expect(host.querySelector('output')).toBeNull()
  expect(host.textContent).toContain('加载中')
  await act(async () => resolveB(response('000001.SZ')))
  await flush()
  await flush()
  expect(plotted().symbol).toBe('000001.SZ')
  expect(host.textContent).not.toContain('浦发银行 ·')
})

it('按截止日截断后再聚合周线，选中结构可定位图表', async () => {
  await click('选择浦发银行')
  await flush()
  const record = host.querySelector<HTMLButtonElement>('[data-structure-id^="stroke:"]')!
  expect(record).toBeTruthy()
  await act(async () => record.click())
  expect(plotted().focusRange).toBeTruthy()
  const cutoff = host.querySelector<HTMLInputElement>('input[type="date"]')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(cutoff, '2026-01-10')
    cutoff.dispatchEvent(new Event('input', { bubbles: true }))
    cutoff.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await flush()
  expect(plotted().data.at(-1).date).toBe('2026-01-10')
  await click('周线')
  expect(plotted().data.length).toBeLessThan(10)
  expect(plotted().focusRange).toBeUndefined()
  expect(host.textContent).toContain('最后一周')
})

it('刷新时OHLC未变化也重算，避免收盘定版后仍显示旧确认范围', async () => {
  await click('选择浦发银行')
  await flush()
  expect(plotted().structureLines.length).toBeGreaterThan(0)
  vi.mocked(api.chanAnalyze).mockImplementationOnce(async (symbol, period, rows) => ({
    ...analysisResponse(symbol, period, rows), structures: [], warnings: ['定版后重新计算'],
  }))
  await click('刷新')
  await flush()
  expect(host.textContent).toContain('定版后重新计算')
  expect(plotted().structureLines).toEqual([])
})

it('计算失败隐藏旧结果，重试后恢复当前周期', async () => {
  await click('选择浦发银行')
  await flush()
  vi.mocked(api.chanAnalyze).mockRejectedValueOnce(new Error('chan.py 无法分析这组K线'))
  await click('周线')
  expect(host.textContent).toContain('缠论计算失败')
  expect(host.querySelector('output')).toBeNull()
  await click('重试')
  await flush()
  expect(host.querySelector('output')).not.toBeNull()
  expect(host.textContent).toContain('最后一周')
})
