// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { RobustnessResults } from './RobustnessResults'
import type { RobustResult } from './api'

let host: HTMLDivElement
let root: Root

afterEach(async () => { await act(async () => root.unmount()); host.remove() })

it('shows development segments and failed holdout without changing frozen recommendation order', async () => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  const result: RobustResult = {
    version: 1,
    time_plan: { development: [1, 2, 3].map(index => ({ id: `dev-${index}`, start: `202${index}-01-01`, end: `202${index}-12-31`, role: 'development' as const })), holdout: { id: 'holdout', start: '2024-01-01', end: '2025-12-31', role: 'holdout' }, diagnostics: [] },
    baseline: [], candidates: [], frozen_candidate_ids: ['first'],
    top3: [{ candidate_id: 'first', robust_score: 0.72, segments: [1, 2, 3].map(index => ({ window_id: `dev-${index}`, metrics: { annualized_return: 0.1, max_drawdown: 0.05, trade_count: 35, baseline_delta: 0.02 }, failure: null })) }],
    holdout: { status: 'failed', usage: 'unknown', failure: '留出验证未通过', results: [{ candidate_id: 'first', metrics: { annualized_return: -0.1, max_drawdown: 0.3, trade_count: 40, baseline_delta: -0.04 } }] }, diagnostics: [], budgets: {},
  }
  await act(async () => root.render(<RobustnessResults result={result} />))
  expect(host.textContent).toContain('推荐 1')
  expect(host.textContent).toContain('72.00%')
  expect(host.textContent).toContain('状态：failed')
  expect(host.textContent).toContain('留出验证未通过')
  expect(host.textContent).toContain('-10.00%')
  expect(host.textContent).toContain('dev-3')
})

it('allows saving a frozen robust recommendation by its rank', async () => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  const result: RobustResult = {
    version: 1,
    time_plan: { development: [], holdout: null, diagnostics: [] },
    baseline: [], candidates: [], frozen_candidate_ids: ['first'],
    top3: [{ candidate_id: 'first', parameters: { window: 12 }, robust_score: 0.72, segments: [] }],
    holdout: { status: 'not_applicable', usage: 'unknown', results: [] }, diagnostics: [], budgets: {},
  }
  const saved: number[] = []
  await act(async () => root.render(<RobustnessResults result={result} onSave={rank => saved.push(rank)} />))
  const button = Array.from(host.querySelectorAll('button')).find(item => item.textContent === '添加到自定义策略')
  expect(button).toBeDefined()
  await act(async () => button?.click())
  expect(saved).toEqual([1])
})
