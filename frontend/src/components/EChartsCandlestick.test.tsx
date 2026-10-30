// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { EChartsCandlestick, type OHLC } from './EChartsCandlestick'

const chart = vi.hoisted(() => ({
  handlers: {} as Record<string, (event?: any) => void>,
  setOption: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  dispatchAction: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
  getZr: () => ({ on: vi.fn(), off: vi.fn() }),
  getOption: () => ({ dataZoom: [{ start: 0, end: 100 }] }),
  containPixel: () => false,
  convertFromPixel: () => [0, 0],
}))

vi.mock('echarts', () => ({ init: () => chart }))

// 超过 COMPACT_THRESHOLD(60): 切标的后 dataZoom 一响就会走紧凑态转换, 进而重写 markPoint
const DAYS = Array.from({ length: 62 }, (_, i) =>
  new Date(Date.UTC(2024, 0, 1 + i)).toISOString().slice(0, 10))
const rows = (base: number): OHLC[] =>
  DAYS.map(date => ({ date, open: base, high: base + 1, low: base - 1, close: base, volume: 1 }))

let host: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  chart.handlers = {}
  chart.setOption.mockClear()
  chart.on.mockImplementation((name: string, callback: (event?: any) => void) => {
    chart.handlers[name] = callback
  })
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

/** 最后一次 setOption 里 K 线的 markPoint (买卖箭头来源) */
function lastMarkPoint(): string {
  const option = chart.setOption.mock.calls.at(-1)?.[0] as any
  const k = option?.series?.find((s: any) => s.name === 'K')
  return JSON.stringify(k?.markPoint ?? null)
}

/** 模拟竖虚线命中某根 K 线 (鼠标在数据区内移动时 echarts 派发的事件) */
async function hoverCandle(index: number) {
  await act(async () => { chart.handlers.updateAxisPointer?.({ axesInfo: [{ value: index }] }) })
}

it('切标的后响应 dataZoom 仍用当前标的的买卖标记, 不回退到上一只', async () => {
  const render = async (symbol: string, data: OHLC[], markerLabel: string, markerDate: string) => {
    await act(async () => root.render(
      <EChartsCandlestick
        data={data}
        markers={[{ date: markerDate, kind: 'buy', label: markerLabel }]}
        symbol={symbol}
        height={400}
        showInfoBar={false}
        visibleBars="all"
        activeIndicators={['vol']}
      />,
    ))
  }

  await render('600000', rows(10), 'A-BUY', DAYS[10])
  await render('000001', rows(100), 'B-SELL', DAYS[20])

  // 切换标的后图表实例被复用, dataZoom 监听仍是最初注册的那个; 首次 setOption 已是当前标的
  expect(lastMarkPoint()).toContain('B-SELL')

  await act(async () => { chart.handlers.dataZoom?.() })

  expect(lastMarkPoint()).toContain('B-SELL')
  expect(lastMarkPoint()).not.toContain('A-BUY')
})

it('切股后鼠标未离开图表, 竖虚线重新命中即恢复「至今/周期」', async () => {
  const render = async (symbol: string) => {
    await act(async () => root.render(
      <EChartsCandlestick data={rows(10)} symbol={symbol} height={400} visibleBars="all" />,
    ))
  }

  await render('600000')
  const surface = host.firstElementChild as HTMLElement
  await act(async () => { surface.dispatchEvent(new MouseEvent('mouseenter')) })
  await hoverCandle(30)
  expect(host.textContent).toContain('至今')

  // 切股: 上一只的悬停上下文作废, 清掉「至今/周期」
  await render('000001')
  expect(host.textContent).not.toContain('至今')

  // 鼠标没离开图表区 (只是切股), 竖虚线重新命中即恢复, 不靠 mouseenter
  await hoverCandle(20)
  expect(host.textContent).toContain('至今')
  expect(host.textContent).toContain('周期')

  // 移出图表区 → 重新收起
  await act(async () => { surface.dispatchEvent(new MouseEvent('mouseleave')) })
  expect(host.textContent).not.toContain('至今')
})

it('结构折线和价格中枢使用主图坐标，关闭后清除，兼容旧时间区间', async () => {
  await act(async () => root.render(
    <EChartsCandlestick data={rows(10)} symbol="600000"
      ranges={[{ start: DAYS[2], end: DAYS[8], low: 10, high: 12, label: 'ZS1' }, { start: DAYS[10], end: DAYS[15] }]}
      structureLines={[{ id: 'bi-1', points: [{ date: DAYS[2], price: 10 }, { date: DAYS[8], price: 12 }], dashed: true }]}
      focusRange={{ start: DAYS[2], end: DAYS[8] }} />,
  ))
  const option = chart.setOption.mock.calls.findLast(c => c[0]?.series?.some((s: any) => s.name === 'K'))?.[0] as any
  const k = option.series.find((s: any) => s.name === 'K')
  expect(k.markArea.data[0][0]).toMatchObject({ xAxis: DAYS[2], yAxis: 10 })
  expect(k.markArea.data[0][1]).toMatchObject({ xAxis: DAYS[8], yAxis: 12 })
  expect(k.markArea.data[1][0].yAxis).toBeUndefined()
  const line = option.series.find((s: any) => s.id === 'structure:bi-1')
  expect(line.data[0]).toEqual([DAYS[2], 10])
  expect(line.data.at(-1)).toEqual([DAYS[8], 12])
  // dataZoom filters by category. Interior samples keep a crossing line visible
  // even when both original endpoints are outside the zoom viewport.
  expect(line.data[3]).toEqual([DAYS[5], 11])
  expect(line.lineStyle.type).toBe('dashed')
  expect(chart.dispatchAction).toHaveBeenCalledWith(expect.objectContaining({ type: 'dataZoom', startValue: 2, endValue: 8 }))
  await act(async () => root.render(<EChartsCandlestick data={rows(100)} symbol="000001" structureLines={[]} ranges={[]} />))
  const next = chart.setOption.mock.calls.at(-1)?.[0] as any
  expect(next.series.some((s: any) => s.id === 'structure:bi-1')).toBe(false)
  expect(next.series.find((s: any) => s.name === 'K').markArea).toBeUndefined()
})
