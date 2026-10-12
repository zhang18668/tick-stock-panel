import { describe, expect, it } from 'vitest'
import { buildLibraryStrategyGroups, buildStrategyGroupViews } from './strategyGrouping'

const strategies = [
  { id: 'a', source: 'custom' },
  { id: 'b', source: 'ai' },
  { id: 'c', source: 'builtin' },
]

describe('buildLibraryStrategyGroups', () => {
  it('orders groups and assigns each available strategy once, leaving invalid references out', () => {
    const groups = buildLibraryStrategyGroups(strategies, [
      { id: 'later', name: '后组', order: 2, strategy_ids: ['b', 'missing', 'a'] },
      { id: 'first', name: '先组', order: 1, strategy_ids: ['a', 'c'] },
    ])

    expect(groups.map(group => [group.id, group.strategyIds])).toEqual([
      ['all', ['a', 'b', 'c']],
      ['first', ['a', 'c']],
      ['later', ['b']],
      ['ungrouped', []],
    ])
  })

  it('keeps empty groups and places strategies without valid membership under ungrouped', () => {
    const groups = buildLibraryStrategyGroups(strategies, [
      { id: 'empty', name: '空组', order: 0, strategy_ids: [] },
      { id: 'invalid', name: '无效引用', order: 1, strategy_ids: ['missing'] },
    ])

    expect(groups.map(group => [group.id, group.strategyIds])).toEqual([
      ['all', ['a', 'b', 'c']],
      ['empty', []],
      ['invalid', []],
      ['ungrouped', ['a', 'b', 'c']],
    ])
  })
})

it('keeps the original source groups and filters strategies in the default mode', () => {
  const groups = buildStrategyGroupViews('source', strategies, [])

  expect(groups.map(group => group.label)).toEqual(['全部', '自定义', 'AI', '叠加', '内置'])
  expect(groups.find(group => group.id === 'custom')?.strategyIds).toEqual(['a'])
  expect(groups.find(group => group.id === 'builtin')?.strategyIds).toEqual(['c'])
})

it('falls back to only all when library groups failed to load', () => {
  const groups = buildStrategyGroupViews('library', strategies, [], true)

  expect(groups).toEqual([{ id: 'all', label: '全部', strategyIds: ['a', 'b', 'c'] }])
})
