import { useMemo } from 'react'
import { EChartsCandlestick, type ChartMarker, type ChartStructureLine, type OHLC } from '@/components/EChartsCandlestick'
import type { ChanStructure, KlineDailyResponse } from '@/lib/api'

export type Layer = 'fractal' | 'stroke' | 'segment' | 'center' | 'signal'
export const LAYERS: { key: Layer; label: string }[] = [
  { key: 'fractal', label: '分型' }, { key: 'stroke', label: '笔' },
  { key: 'segment', label: '线段' }, { key: 'center', label: '中枢' }, { key: 'signal', label: '买卖点' },
]

export function ChartPill({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return <button type="button" aria-pressed={active} onClick={onClick}
    className={`rounded px-2 py-0.5 font-mono text-[10px] transition-colors ${active ? 'bg-accent/20 text-accent' : 'bg-elevated text-muted hover:text-secondary'}`}>
    {children}
  </button>
}

export function ChanChart({ rows, structures, layers, indicators, symbol, selected, stockInfo, onDateClick }: {
  rows: OHLC[]; structures: ChanStructure[]; layers: Layer[]; indicators: string[]; symbol: string
  selected?: ChanStructure; stockInfo?: KlineDailyResponse['stock_info']; onDateClick: (date: string) => void
}) {
  const overlays = useMemo(() => {
    const visible = structures.filter(s => layers.includes(s.kind))
    const structureLines: ChartStructureLine[] = visible.filter(s => s.kind === 'stroke' || s.kind === 'segment').map(s => ({
      id: s.id, label: `${s.label}${s.confirmedAt ? '' : '（未确认）'}`,
      points: [s.start, s.end], color: s.kind === 'stroke' ? '#8B5CF6' : '#3B82F6',
      width: s.kind === 'stroke' ? 1 : 2.5, dashed: !s.confirmedAt,
    }))
    const markers: ChartMarker[] = visible.filter(s => s.kind === 'signal' || s.kind === 'fractal').map(s => ({
      date: s.end.date,
      kind: s.kind === 'fractal' ? 'neutral' : s.label.startsWith('B') ? 'buy' : 'sell',
      label: `${s.label}${s.kind === 'signal' && !s.confirmedAt ? '?' : ''}`,
      above: s.kind === 'fractal' ? s.label === '顶' : undefined,
    }))
    const ranges = visible.filter(s => s.kind === 'center').map(s => ({
      start: s.start.date, end: s.end.date, low: s.low, high: s.high,
      label: `${s.label} ${s.low?.toFixed(2)}–${s.high?.toFixed(2)}${s.confirmedAt ? '' : ' 未确认'}`,
      color: 'rgba(139,92,246,0.10)',
    }))
    return { structureLines, markers, ranges }
  }, [structures, layers])
  const focusRange = useMemo(() => {
    if (!selected) return undefined
    const first = Math.max(0, selected.start.index - 5)
    const last = Math.min(rows.length - 1, selected.end.index + 5)
    return { start: rows[first].date, end: rows[last].date }
  }, [selected, rows])
  return <EChartsCandlestick key={symbol} data={rows} symbol={symbol} height={640}
    {...overlays} focusRange={focusRange} activeIndicators={indicators}
    showMA showInfoBar stockInfo={stockInfo} visibleBars={120} onDateClick={onDateClick} />
}
