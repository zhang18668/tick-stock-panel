export type LibraryStrategyGroup = {
  id: string
  name: string
  order: number
  strategy_ids: string[]
}

export type StrategyChoice = { id: string; source: string }
export type StrategyGroupView = { id: string; label: string; strategyIds: string[] }
export type StrategyGroupingMode = 'source' | 'library'

export const SOURCE_STRATEGY_GROUPS: StrategyGroupView[] = [
  { id: 'all', label: '全部', strategyIds: [] },
  { id: 'custom', label: '自定义', strategyIds: [] },
  { id: 'ai', label: 'AI', strategyIds: [] },
  { id: 'composite', label: '叠加', strategyIds: [] },
  { id: 'builtin', label: '内置', strategyIds: [] },
]

export function buildStrategyGroupViews(
  mode: StrategyGroupingMode,
  strategies: StrategyChoice[],
  libraryGroups: LibraryStrategyGroup[],
  libraryGroupsError = false,
): StrategyGroupView[] {
  if (mode === 'library') {
    return libraryGroupsError
      ? [{ id: 'all', label: '全部', strategyIds: strategies.map(strategy => strategy.id) }]
      : buildLibraryStrategyGroups(strategies, libraryGroups)
  }

  return SOURCE_STRATEGY_GROUPS.map(group => ({
    ...group,
    strategyIds: group.id === 'all'
      ? strategies.map(strategy => strategy.id)
      : strategies.filter(strategy => strategy.source === group.id).map(strategy => strategy.id),
  }))
}

export function buildLibraryStrategyGroups(
  strategies: StrategyChoice[],
  groups: LibraryStrategyGroup[],
): StrategyGroupView[] {
  const availableIds = new Set(strategies.map(strategy => strategy.id))
  const assignedIds = new Set<string>()
  const orderedGroups = groups
    .map((group, index) => ({ group, index }))
    .sort((a, b) => a.group.order - b.group.order || a.index - b.index)
    .map(({ group }) => ({
      id: group.id,
      label: group.name,
      strategyIds: group.strategy_ids.filter(id => {
        if (!availableIds.has(id) || assignedIds.has(id)) return false
        assignedIds.add(id)
        return true
      }),
    }))

  return [
    { id: 'all', label: '全部', strategyIds: strategies.map(strategy => strategy.id) },
    ...orderedGroups,
    {
      id: 'ungrouped',
      label: '未分组',
      strategyIds: strategies.map(strategy => strategy.id).filter(id => !assignedIds.has(id)),
    },
  ]
}
