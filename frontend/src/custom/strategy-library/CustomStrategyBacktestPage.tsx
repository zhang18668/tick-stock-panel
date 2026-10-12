import { BookOpenCheck } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { QK } from '../../lib/queryKeys'
import { StrategyBacktest } from '../../pages/backtest/StrategyBacktest'
import { strategyLibraryApi } from './api'

export function CustomStrategyBacktestPage() {
  const groupsQuery = useQuery({
    queryKey: QK.strategyLibrary,
    queryFn: strategyLibraryApi.library,
    staleTime: 30_000,
  })

  return <main className="mx-auto max-w-7xl space-y-4 p-4 pb-12 sm:p-6">
    <header>
      <div className="flex items-center gap-2 text-primary"><BookOpenCheck size={18} /><span className="text-xs font-semibold uppercase tracking-widest">Custom strategies</span></div>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">自定义策略</h1>
      <p className="mt-1 text-sm text-muted">按策略库分组选择策略，并使用统一回测工作区运行和查看结果。</p>
    </header>
    <StrategyBacktest
      strategyGroupingMode="library"
      libraryGroups={groupsQuery.data?.groups ?? []}
      libraryGroupsLoading={groupsQuery.isPending}
      libraryGroupsError={groupsQuery.isError ? groupsQuery.error.message : undefined}
      onRetryLibraryGroups={() => { void groupsQuery.refetch() }}
    />
  </main>
}
