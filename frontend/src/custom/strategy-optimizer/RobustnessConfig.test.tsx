// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RobustnessConfig } from './RobustnessConfig'

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
})

describe('RobustnessConfig', () => {
  it('shows trading-date splits, budget and unavailable-run blocker from preview', () => {
    const host = document.createElement('div')
    const root: Root = createRoot(host)
    act(() => root.render(<RobustnessConfig
      layout="holdout" holdoutUsage="unknown" neighborBudget={20} previewError=""
      preview={{
        strategy_id: 'demo',
        time_plan: {
          development: [{ id: 'd1', start: '2020-01-01', end: '2020-03-31', role: 'development' }],
          holdout: { id: 'h1', start: '2024-01-01', end: '2025-12-31', role: 'holdout' },
          diagnostics: [],
        },
        calendar_source: 'normalized_repository_daily_dates',
        calendar_coverage: { requested_start: '2020-01-01', requested_end: '2025-12-31', covered_start: '2020-01-01', covered_end: '2025-12-31', trading_dates: 1500 },
        data_generation: 'g1',
        budgets: { main_candidates: 100, neighbor_candidates: 20, estimated_backtests: 400 },
        holdout_usage: 'unknown', warnings: [],
        strategy_snapshot_available: false, run_available: false,
        run_blocker: 'strategy snapshot execution is unavailable',
      }}
      onLayoutChange={vi.fn()} onHoldoutUsageChange={vi.fn()} onNeighborBudgetChange={vi.fn()} onPreview={vi.fn()}
    />))

    expect(host.textContent).toContain('开发段 1：2020-01-01 至 2020-03-31')
    expect(host.textContent).toContain('预计回测调用上限：400')
    expect(host.querySelector('[role="status"]')?.textContent).toContain('strategy snapshot execution is unavailable')
    act(() => root.unmount())
    host.remove()
  })

  it('reports changes to layout and requests a preview', () => {
    const onLayoutChange = vi.fn()
    const onPreview = vi.fn()
    const host = document.createElement('div')
    const root = createRoot(host)
    act(() => root.render(<RobustnessConfig layout="holdout" holdoutUsage="unknown" neighborBudget={20} preview={null} previewError="" onLayoutChange={onLayoutChange} onHoldoutUsageChange={vi.fn()} onNeighborBudgetChange={vi.fn()} onPreview={onPreview} />))

    const layout = host.querySelector('select')!
    Object.defineProperty(layout, 'value', { value: 'diagnostic', configurable: true })
    act(() => layout.dispatchEvent(new Event('change', { bubbles: true })))
    act(() => host.querySelector('button')!.click())

    expect(onLayoutChange).toHaveBeenCalledWith('diagnostic')
    expect(onPreview).toHaveBeenCalledOnce()
    act(() => root.unmount())
    host.remove()
  })
})
